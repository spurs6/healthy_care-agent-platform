"""
自进化医疗循证Agent - 核心Agent Loop

架构:
1. LangChain tool calling驱动Agent循环
2. LLM自主决策调用工具（本地检索、外部搜索、证据评估）
3. 收集证据后用现有SiliconFlow客户端流式生成答案
4. 自动记录经验和知识缺口

Phase 1: 工具调用 + 外部检索
Phase 2: 经验记忆 + 策略推荐 + 缺口记录
"""
import json
import uuid
import asyncio
from datetime import datetime
from typing import AsyncIterator, Dict, Any, List, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    SystemMessage, HumanMessage, AIMessage, ToolMessage
)

from backend.config import (
    SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, SILICONFLOW_MODEL,
    SYSTEM_PROMPT, ALLOWED_DISEASES, REJECT_MESSAGE,
    LLM_MAX_TOKENS, LLM_TEMPERATURE
)
from backend.agent.tools import ALL_TOOLS
from backend.agent.memory_bank import memory_bank
from backend.agent.gap_logger import gap_logger
from backend.agent.reasoning_evolution import reasoning_evolution
from backend.agent.safety_guard import safety_guard, RiskLevel
from backend.llm_service.llm_client import SiliconFlowClient, DomainFilter
from backend.llm_service import llm_service


# ==================== Agent系统提示 ====================
AGENT_SYSTEM_PROMPT = """你是一个自进化医疗循证Agent，面向临床医生提供心脑血管、高血压、高血脂、糖尿病的循证证据问答。

## 工作流程（严格按序执行）
1. 调用 query_classifier 分类用户问题类型和疾病领域
2. 调用 local_search 搜索本地知识库
3. 检查检索结果：
   - 如果 gap_detected=true 或 max_similarity<0.7，调用 external_search 补充外部最新文献
4. 调用 evidence_evaluator 评估证据充分性
5. 如果证据充分（sufficient=true），直接生成答案，不要再调用工具
6. 如果证据不足，可以用不同关键词再调 external_search 一次

## 重要规则
- 所有临床结论必须基于检索到的证据，禁止编造
- 优先采信临床指南 > RCT/Meta分析 > 观察性研究
- 引用格式：[doc_id]
- 若所有证据均无法回答，输出：【暂无匹配的权威临床循证证据，无法给出诊疗建议】
- 回答结构：①核心诊疗结论 ②分点附带引用标注 ③文末引用来源附录
- 双语兼容：中文指南优先，英文文献结论翻译为规范医学中文
"""


class MedicalAgent:
    """自进化医疗循证Agent"""

    def __init__(self):
        # LangChain LLM (用于工具调用决策)
        self.llm = ChatOpenAI(
            model=SILICONFLOW_MODEL,
            api_key=SILICONFLOW_API_KEY,
            base_url=SILICONFLOW_BASE_URL,
            temperature=0.1,
            max_tokens=LLM_MAX_TOKENS
        )
        self.tools_by_name = {t.name: t for t in ALL_TOOLS}
        self.llm_with_tools = self.llm.bind_tools(ALL_TOOLS)

        # 现有基础设施（用于流式生成最终答案）
        self.llm_client = SiliconFlowClient()
        self.domain_filter = DomainFilter()

        # Phase 2 组件
        self.memory = memory_bank
        self.gap_logger = gap_logger

        # Phase 3 组件
        self.reasoning = reasoning_evolution
        self.safety = safety_guard

    # ==================== 核心流式问答 ====================
    async def stream_answer(self, query: str) -> AsyncIterator[dict]:
        """
        Agent流式问答 - SSE格式输出

        流程:
        1. 领域检查
        2. Agent循环（工具调用收集证据）
        3. 流式生成最终答案
        4. 记录经验和缺口
        """
        # 领域检查
        if not self.domain_filter.is_allowed_domain(query):
            yield {"type": "text", "content": self.domain_filter.get_reject_message()}
            yield {"type": "done", "message": "回答完成"}
            return

        yield {"type": "status", "message": "Agent分析问题中..."}

        # Phase 1: Agent循环收集证据
        all_evidence = []
        tool_calls_log = []
        gap_detected = False
        gap_info = {"max_similarity": 0.0, "domain": "", "external_source": "", "external_results_count": 0}
        query_type = "treatment"
        max_similarity = 0.0

        try:
            messages = [
                SystemMessage(content=AGENT_SYSTEM_PROMPT),
                HumanMessage(content=query)
            ]

            for iteration in range(5):  # 最多5轮工具调用
                response = await self.llm_with_tools.ainvoke(messages)
                messages.append(response)

                if not response.tool_calls:
                    # LLM不再调用工具，准备生成答案
                    break

                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]

                    yield {"type": "tool_call", "tool": tool_name, "input": tool_args}

                    # 执行工具
                    tool_result = self._execute_tool(tool_name, tool_args)
                    messages.append(ToolMessage(
                        content=tool_result,
                        tool_call_id=tool_call["id"]
                    ))

                    # 解析工具结果
                    try:
                        result_data = json.loads(tool_result)
                    except json.JSONDecodeError:
                        result_data = {"message": tool_result[:200]}

                    # 收集证据和缺口信息
                    if tool_name == "query_classifier":
                        query_type = result_data.get("query_type", "treatment")
                        diseases = result_data.get("diseases", [])
                        gap_info["domain"] = diseases[0] if diseases else ""

                    elif tool_name == "local_search":
                        max_similarity = result_data.get("max_similarity", 0.0)
                        gap_info["max_similarity"] = max_similarity
                        if result_data.get("gap_detected"):
                            gap_detected = True
                            gap_info["gap_reason"] = result_data.get("gap_reason", "")
                        local_ev = result_data.get("evidence", [])
                        for ev in local_ev:
                            ev["evidence_origin"] = "local"
                        all_evidence.extend(local_ev)
                        yield {"type": "chunks", "data": local_ev[:5]}

                    elif tool_name == "external_search":
                        ext_ev = result_data.get("evidence", [])
                        for ev in ext_ev:
                            ev["evidence_origin"] = "external"
                        all_evidence.extend(ext_ev)
                        yield {"type": "chunks", "data": ext_ev[:3]}
                        if gap_detected:
                            gap_info["external_source"] = result_data.get("sources", {}).get("pubmed", 0) > 0 and "pubmed" or "europepmc"
                            gap_info["external_results_count"] = result_data.get("total", 0)

                    tool_calls_log.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result_summary": result_data.get("message", ""),
                        "timestamp": datetime.now().isoformat()
                    })

                    yield {
                        "type": "tool_result",
                        "tool": tool_name,
                        "summary": result_data.get("message", "")
                    }

        except Exception as e:
            print(f"[Agent] 工具调用阶段异常: {e}")
            yield {"type": "status", "message": "Agent工具调用异常，回退到直接检索模式..."}

        # Phase 2: 流式生成最终答案
        yield {"type": "status", "message": "正在生成循证答案..."}

        if not all_evidence:
            yield {"type": "text", "content": REJECT_MESSAGE}
            yield {"type": "done", "message": "回答完成"}
            return

        # 构建最终Prompt并流式生成（含推理原则）
        prompt = self._build_final_prompt(query, all_evidence, query_type, gap_info.get("domain", ""))

        async for chunk in self.llm_client.stream_chat(prompt):
            yield {"type": "text", "content": chunk}

        # 参考文献附录
        refs = self._format_references(all_evidence)
        if refs:
            yield {"type": "references", "content": refs}

        # Phase 3: 记录经验和缺口（异步，不阻塞响应）
        self._record_experience(
            query, query_type, tool_calls_log,
            max_similarity, gap_detected, gap_info, all_evidence
        )

        yield {"type": "done", "message": "回答完成"}

    # ==================== 工具执行 ====================
    def _execute_tool(self, tool_name: str, tool_args: Dict) -> str:
        """执行工具调用"""
        tool = self.tools_by_name.get(tool_name)
        if not tool:
            return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)

        try:
            # LangChain @tool decorated functions are sync
            result = tool.invoke(tool_args)
            return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ==================== Prompt构建 ====================
    def _build_final_prompt(self, query: str, evidence: List[Dict],
                            query_type: str = "treatment",
                            disease_tags: List[str] = None) -> str:
        """构建最终答案生成Prompt（含推理原则指导）"""
        evidence_text = self._format_evidence_for_prompt(evidence)

        # 检索匹配的推理原则
        principles = self.reasoning.retrieve_principles(query_type, disease_tags, limit=3)
        principle_text = self.reasoning.format_principles_for_agent(principles)

        # 记录原则使用
        used_principle_ids = []
        for p in principles:
            # 安全检查：置信度足够才自动应用
            is_safe, _ = self.safety.validate_principle_application(p.get("confidence", 0.5))
            if is_safe:
                used_principle_ids.append(p["principle_id"])

        base_prompt = SYSTEM_PROMPT.format(
            retrieved_chunks=evidence_text,
            user_query=query
        )

        # 注入推理原则
        if principle_text:
            base_prompt = principle_text + "\n\n" + base_prompt

        # 存储使用的原则ID，用于后续置信度更新
        self._used_principle_ids = used_principle_ids

        return base_prompt

    def _format_evidence_for_prompt(self, evidence: List[Dict]) -> str:
        """格式化证据片段（统一本地和外部格式）"""
        formatted = []
        for i, ev in enumerate(evidence[:10]):  # 最多10条
            origin = ev.get("evidence_origin", "local")
            doc_id = ev.get("doc_id", f"ev_{i}")
            title = ev.get("title", "N/A")
            evidence_level = ev.get("evidence_level", "3B")
            source = ev.get("source_type") or ev.get("source", "unknown")
            text = ev.get("text_preview") or ev.get("abstract_preview", "")

            evidence_str = f"""
【证据片段{i+1}】({'本地' if origin == 'local' else '外部实时检索'})
来源：{source} | 标题：{title} | 证据等级：{evidence_level}
引用ID：[{doc_id}]

内容：
{text[:500]}...

---"""
            formatted.append(evidence_str)

        return '\n'.join(formatted)

    def _format_references(self, evidence: List[Dict]) -> str:
        """格式化参考文献"""
        if not evidence:
            return ""

        refs = ["\n\n---\n**参考文献**\n"]
        for i, ev in enumerate(evidence[:10]):
            origin = "本地" if ev.get("evidence_origin") == "local" else "外部"
            pmid = ev.get("pmid", "")
            pmid_str = f" | PMID: {pmid}" if pmid else ""
            ref = f"""
[{i+1}] {ev.get('doc_id', '')}
- 来源：{origin} | {ev.get('source_type') or ev.get('source', '')}{pmid_str}
- 标题：{ev.get('title', 'N/A')}
- 证据等级：{ev.get('evidence_level', 'N/A')}
- 相似度/相关性：{ev.get('score', 'N/A')}
"""
            refs.append(ref)

        return '\n'.join(refs)

    # ==================== 经验记录 ====================
    def _record_experience(self, query: str, query_type: str,
                           tool_calls: List[Dict], max_similarity: float,
                           gap_detected: bool, gap_info: Dict,
                           evidence: List[Dict]):
        """记录经验和缺口（非阻塞）"""
        try:
            # 记录经验
            strategy = {
                "bm25_weight": 0.4,
                "vector_weight": 0.6,
                "rerank_threshold": 0.1,
                "recall_top_k": 10,
                "final_top_n": 8,
                "use_external_search": gap_detected
            }

            outcome = {
                "max_similarity": max_similarity,
                "evidence_count": len(evidence),
                "gap_detected": gap_detected,
                "external_used": gap_info.get("external_results_count", 0) > 0,
                "evidence_levels": [ev.get("evidence_level", "") for ev in evidence[:8]]
            }

            # 自动评估分数
            auto_score = self._auto_evaluate(query, evidence, max_similarity)

            # 提取疾病标签
            diseases = []
            query_lower = query.lower()
            for disease in ALLOWED_DISEASES:
                if disease.lower() in query_lower:
                    diseases.append(disease)

            self.memory.record_experience(
                query=query,
                query_type=query_type,
                disease_tags=diseases,
                strategy=strategy,
                outcome=outcome,
                tool_calls=tool_calls,
                answer="",  # 答案文本太大，不存储
                auto_eval_score=auto_score
            )

            # 记录知识缺口
            if gap_detected:
                gap_type = "no_result" if max_similarity == 0 else "low_similarity"
                self.gap_logger.log_gap(
                    query=query,
                    gap_type=gap_type,
                    max_similarity=max_similarity,
                    domain=gap_info.get("domain", ""),
                    external_source=gap_info.get("external_source", ""),
                    external_results_count=gap_info.get("external_results_count", 0),
                    fetched_articles=[ev.get("doc_id") for ev in evidence if ev.get("evidence_origin") == "external"]
                )

            # 安全审计：记录经验记录操作
            self.safety.log_evolution_action(
                action_type="experience_record",
                target_table="table_agent_experience",
                target_id=query[:50],
                change_summary=f"记录{query_type}类型经验, 评分={auto_score}",
                risk_level=RiskLevel.LOW
            )

            # 推理原则置信度更新
            used_ids = getattr(self, "_used_principle_ids", [])
            for pid in used_ids:
                # 高分经验 → 原则使用成功；低分 → 失败
                self.reasoning.update_principle_confidence(pid, success=auto_score >= 0.6)

        except Exception as e:
            print(f"[Agent] 记录经验失败: {e}")

    def _auto_evaluate(self, query: str, evidence: List[Dict], max_similarity: float) -> float:
        """自动评估本次问答质量（简单规则）"""
        score = 0.0

        # 证据数量
        ev_count = len(evidence)
        if ev_count >= 5:
            score += 0.3
        elif ev_count >= 3:
            score += 0.2
        elif ev_count >= 1:
            score += 0.1

        # 最高相似度
        if max_similarity >= 0.8:
            score += 0.3
        elif max_similarity >= 0.7:
            score += 0.2
        elif max_similarity >= 0.5:
            score += 0.1

        # 证据等级多样性
        levels = set(ev.get("evidence_level", "") for ev in evidence)
        if "1A" in levels:
            score += 0.2
        if "1B" in levels:
            score += 0.1

        # 来源多样性
        sources = set(ev.get("source_type") or ev.get("source", "") for ev in evidence)
        if len(sources) >= 2:
            score += 0.1

        return min(round(score, 2), 1.0)

    # ==================== 策略推荐（Phase 2） ====================
    def get_recommended_strategy(self, query_type: str) -> Dict[str, Any]:
        """获取推荐策略"""
        return self.memory.recommend_strategy(query_type)

    def get_evolution_status(self) -> Dict[str, Any]:
        """获取自进化状态"""
        from backend.agent.strategy_evolution import strategy_evolution
        return strategy_evolution.get_evolution_report()


# 全局实例（延迟初始化）
_medical_agent: Optional[MedicalAgent] = None


def get_medical_agent() -> MedicalAgent:
    """获取Agent实例（延迟初始化）"""
    global _medical_agent
    if _medical_agent is None:
        _medical_agent = MedicalAgent()
    return _medical_agent


# 兼容性别名
medical_agent = None  # 延迟初始化，通过get_medical_agent()访问
