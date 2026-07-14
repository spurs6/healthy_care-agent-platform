"""
OpenEvidence 临床证据助手 - LLM循证问答模块
硅基流动API调用、流式SSE返回、引用格式化
"""
import json
import uuid
import httpx
from typing import List, Dict, Any, Optional, AsyncIterator
from datetime import datetime

from backend.config import (
    SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, SILICONFLOW_MODEL,
    SYSTEM_PROMPT, REJECT_MESSAGE, ALLOWED_DISEASES, ALLOWED_MEDICAL_TERMS,
    LLM_MAX_TOKENS, LLM_TEMPERATURE, LLM_STREAM_TIMEOUT
)
from backend.db_store import RetrievedChunk, ChatResponse


class DomainFilter:
    """领域过滤器"""
    
    def is_allowed_domain(self, query: str) -> bool:
        """
        检查问题是否在允许的疾病领域内
        
        Args:
            query: 用户查询
        
        Returns:
            是否允许作答
        """
        query_lower = query.lower()
        
        # 检查是否包含允许的疾病关键词
        for disease in ALLOWED_DISEASES:
            if disease.lower() in query_lower:
                return True
        
        # 检查是否包含医学通用词汇（药物名、诊疗操作、检查指标等）
        for term in ALLOWED_MEDICAL_TERMS:
            if term.lower() in query_lower:
                return True
        
        return False
    
    def get_reject_message(self) -> str:
        """获取领域拒绝消息"""
        return f"您好，本助手专注于高血压、高血脂、2型糖尿病、心脑血管合并症的临床循证问答。您的问题超出本助手服务范围，暂无法作答。如有上述疾病相关问题，欢迎继续提问。"


class PromptBuilder:
    """循证Prompt构建器"""
    
    def build_evidence_prompt(self, query: str, chunks: List[RetrievedChunk]) -> str:
        """
        构建循证问答Prompt
        
        Args:
            query: 用户查询
            chunks: 检索到的证据片段
        
        Returns:
            完整Prompt
        """
        # 格式化证据片段
        evidence_text = self._format_chunks(chunks)
        
        # 组装Prompt
        prompt = SYSTEM_PROMPT.format(
            retrieved_chunks=evidence_text,
            user_query=query
        )
        
        return prompt
    
    def _format_chunks(self, chunks: List[RetrievedChunk]) -> str:
        """格式化证据片段"""
        formatted = []
        for i, chunk in enumerate(chunks):
            evidence_str = f"""
【证据片段{i+1}】
来源：{chunk['source_type']} | 标题：{chunk['title']} | 证据等级：{chunk['evidence_level']} | 页码：{chunk['page']}
引用ID：[{chunk['doc_id']}]

内容：
{chunk['text'][:500]}...

---"""
            formatted.append(evidence_str)
        
        return '\n'.join(formatted)


class SiliconFlowClient:
    """硅基流动API客户端"""
    
    def __init__(self):
        self.api_key = SILICONFLOW_API_KEY
        self.base_url = SILICONFLOW_BASE_URL
        self.model = SILICONFLOW_MODEL
        self.max_tokens = LLM_MAX_TOKENS
        self.temperature = LLM_TEMPERATURE
        self.timeout = LLM_STREAM_TIMEOUT
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def stream_chat(self, prompt: str) -> AsyncIterator[str]:
        """
        流式调用LLM
        
        Args:
            prompt: 完整Prompt
        
        Yields:
            生成的文本片段
        """
        if not self.api_key:
            yield "[错误：未配置硅基流动API密钥，请设置SILICONFLOW_API_KEY环境变量]"
            return
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": True
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._get_headers(),
                    json=payload
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        yield f"[LLM调用失败：{response.status_code}]"
                        return
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]  # 移除 "data: " 前缀
                            if data_str == "[DONE]":
                                break
                            
                            try:
                                data = json.loads(data_str)
                                content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
                                
        except httpx.TimeoutException:
            yield "[LLM响应超时，请稍后重试]"
        except Exception as e:
            yield f"[LLM调用异常：{str(e)}]"
    
    async def chat(self, prompt: str) -> str:
        """非流式调用LLM"""
        full_response = []
        for chunk in await self._collect_stream(self.stream_chat(prompt)):
            full_response.append(chunk)
        return ''.join(full_response)
    
    async def _collect_stream(self, stream: AsyncIterator[str]) -> List[str]:
        """收集流式响应"""
        chunks = []
        async for chunk in stream:
            chunks.append(chunk)
        return chunks


class LLMService:
    """LLM问答服务"""
    
    def __init__(self):
        self.domain_filter = DomainFilter()
        self.prompt_builder = PromptBuilder()
        self.llm_client = SiliconFlowClient()
    
    async def answer(self, query: str, chunks: List[RetrievedChunk], 
                     has_evidence: bool) -> ChatResponse:
        """
        执行问答
        
        Args:
            query: 用户查询
            chunks: 检索结果
            has_evidence: 是否有有效证据
        
        Returns:
            问答响应
        """
        # 1. 领域检查
        if not self.domain_filter.is_allowed_domain(query):
            return {
                "answer": self.domain_filter.get_reject_message(),
                "chunks": [],
                "has_evidence": False,
                "query": query,
                "timestamp": datetime.now().isoformat()
            }
        
        # 2. 无证据拒答
        if not has_evidence or not chunks:
            return {
                "answer": REJECT_MESSAGE,
                "chunks": [],
                "has_evidence": False,
                "query": query,
                "timestamp": datetime.now().isoformat()
            }
        
        # 3. 构建Prompt
        prompt = self.prompt_builder.build_evidence_prompt(query, chunks)
        
        # 4. 调用LLM生成答案
        answer_text = await self.llm_client.chat(prompt)
        
        return {
            "answer": answer_text,
            "chunks": chunks,
            "has_evidence": True,
            "query": query,
            "timestamp": datetime.now().isoformat()
        }
    
    async def stream_answer(self, query: str, chunks: List[RetrievedChunk],
                           has_evidence: bool) -> AsyncIterator[str]:
        """
        流式返回答案
        
        Args:
            query: 用户查询
            chunks: 检索结果
            has_evidence: 是否有有效证据
        
        Yields:
            答案文本片段
        """
        # 1. 领域检查
        if not self.domain_filter.is_allowed_domain(query):
            yield self.domain_filter.get_reject_message()
            return
        
        # 2. 无证据拒答
        if not has_evidence or not chunks:
            yield REJECT_MESSAGE
            return
        
        # 3. 先返回检索结果信息
        yield f"【检索到{len(chunks)}条临床循证证据】\n\n"
        yield "---\n\n"
        
        # 4. 构建Prompt并流式生成
        prompt = self.prompt_builder.build_evidence_prompt(query, chunks)
        
        async for chunk in self.llm_client.stream_chat(prompt):
            yield chunk
    
    def format_references(self, chunks: List[RetrievedChunk]) -> str:
        """
        格式化参考文献附录
        
        Args:
            chunks: 引用的证据片段
        
        Returns:
            格式化的参考文献列表
        """
        if not chunks:
            return ""
        
        refs = ["\n\n---\n**参考文献**\n"]
        
        for i, chunk in enumerate(chunks):
            ref = f"""
[{i+1}] {chunk['doc_id']}
- 来源：{chunk['source_type']}
- 标题：{chunk['title']}
- 证据等级：{chunk['evidence_level']}
- 相关性分数：{chunk['score']:.2f}
"""
            refs.append(ref)
        
        return '\n'.join(refs)


# 全局实例
domain_filter = DomainFilter()
prompt_builder = PromptBuilder()
llm_client = SiliconFlowClient()
llm_service = LLMService()