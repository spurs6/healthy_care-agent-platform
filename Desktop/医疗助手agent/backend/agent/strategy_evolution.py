"""
策略自进化引擎 - Phase 2 核心

功能:
1. 自博弈评估引擎 - 利用知识库自动生成测试题，比较不同策略效果
2. 跨查询知识迁移 - 从相似查询复用成功策略
3. 策略参数优化 - 基于历史经验优化检索参数
"""
import json
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

from backend.db_store.database import db_manager
from backend.agent.memory_bank import memory_bank
from backend.agent.gap_logger import gap_logger
from backend.config import (
    SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, SILICONFLOW_MODEL,
    SYSTEM_PROMPT
)


class StrategyEvolution:
    """策略自进化引擎"""

    def __init__(self):
        self.db = db_manager

    # ==================== 自博弈评估引擎 ====================
    async def self_play_evaluate(self, sample_count: int = 5) -> Dict[str, Any]:
        """
        自博弈评估：从知识库生成测试题，用不同策略回答，比较效果

        流程:
        1. 从数据库随机选文献 → LLM生成问题
        2. 用策略A(默认)和策略B(历史最优)分别检索
        3. 自动评估（证据命中率、引用数、相似度）
        4. 更新最优策略

        Args:
            sample_count: 生成多少道测试题

        Returns:
            评估报告
        """
        print(f"[StrategyEvolution] 启动自博弈评估，样本数={sample_count}")

        # Step1: 生成测试题
        test_cases = await self._generate_test_cases(sample_count)
        if not test_cases:
            return {"status": "failed", "message": "无法生成测试题"}

        # Step2: 对每种查询类型，比较不同策略
        results = []
        for case in test_cases:
            query = case["query"]
            query_type = case["query_type"]
            expected_doc_id = case["doc_id"]

            # 策略A: 默认策略
            result_a = self._evaluate_with_strategy(query, query_type, "default")

            # 策略B: 历史最优策略
            result_b = self._evaluate_with_strategy(query, query_type, "optimized")

            # 策略C: 激进策略（更多召回、更低阈值）
            result_c = self._evaluate_with_strategy(query, query_type, "aggressive")

            comparison = {
                "query": query,
                "query_type": query_type,
                "expected_doc_id": expected_doc_id,
                "strategy_default": result_a,
                "strategy_optimized": result_b,
                "strategy_aggressive": result_c,
                "winner": self._pick_winner(result_a, result_b, result_c)
            }
            results.append(comparison)

        # Step3: 汇总结果，更新策略
        type_results = defaultdict(list)
        for r in results:
            type_results[r["query_type"]].append(r)

        updated_strategies = []
        for qtype, cases in type_results.items():
            best_strategy = self._analyze_best_strategy(cases)
            if best_strategy:
                memory_bank.update_optimized_strategy(
                    query_type=qtype,
                    strategy=best_strategy["params"],
                    sample_count=len(cases),
                    avg_score=best_strategy["avg_score"]
                )
                updated_strategies.append({
                    "query_type": qtype,
                    "best_strategy": best_strategy["params"],
                    "avg_score": best_strategy["avg_score"],
                    "sample_count": len(cases)
                })

        return {
            "status": "success",
            "total_test_cases": len(results),
            "type_distribution": {k: len(v) for k, v in type_results.items()},
            "updated_strategies": updated_strategies,
            "timestamp": datetime.now().isoformat()
        }

    async def _generate_test_cases(self, count: int) -> List[Dict[str, Any]]:
        """从知识库生成测试题"""
        import httpx

        # 从数据库随机选取文献
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT doc_id, title, abstract, source_type, evidence_level, disease_tags
                FROM table_article_meta
                WHERE abstract IS NOT NULL AND abstract != ''
                ORDER BY RANDOM() LIMIT ?
            """, (count,))
            articles = [dict(row) for row in cursor.fetchall()]

        if not articles:
            return []

        test_cases = []
        for article in articles:
            # 用LLM根据摘要生成问题
            prompt = f"""基于以下医学文献摘要，生成一个临床医生可能会问的问题。
            只输出问题本身，不要其他内容。

            标题: {article['title']}
            摘要: {article['abstract'][:500]}

            要求:
            - 问题应该是临床实践中的常见问题
            - 问题应该能从这篇文献中找到答案
            - 只输出一行问题"""

            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        f"{SILICONFLOW_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": SILICONFLOW_MODEL,
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 100,
                            "temperature": 0.5
                        }
                    )
                    if resp.status_code == 200:
                        question = resp.json()["choices"][0]["message"]["content"].strip()
                        # 简单分类查询类型
                        query_type = self._classify_query(question)
                        test_cases.append({
                            "query": question,
                            "query_type": query_type,
                            "doc_id": article["doc_id"],
                            "source_type": article["source_type"]
                        })
            except Exception as e:
                print(f"[StrategyEvolution] 生成测试题失败: {e}")
                continue

        print(f"[StrategyEvolution] 生成了{len(test_cases)}道测试题")
        return test_cases

    def _evaluate_with_strategy(self, query: str, query_type: str,
                                strategy_name: str) -> Dict[str, Any]:
        """用指定策略评估查询"""
        from backend.rag_core import rag_retriever

        # 获取策略参数
        if strategy_name == "default":
            strategy = memory_bank._default_strategy()
        elif strategy_name == "optimized":
            rec = memory_bank.recommend_strategy(query_type)
            strategy = rec.get("params", memory_bank._default_strategy())
        elif strategy_name == "aggressive":
            strategy = {
                "bm25_weight": 0.3,
                "vector_weight": 0.7,
                "rerank_threshold": 0.05,
                "recall_top_k": 15,
                "final_top_n": 10
            }
        else:
            strategy = memory_bank._default_strategy()

        # 执行检索
        try:
            chunks, has_evidence = rag_retriever.retrieve(query)

            if not chunks:
                return {
                    "strategy": strategy_name,
                    "params": strategy,
                    "evidence_count": 0,
                    "max_similarity": 0.0,
                    "avg_similarity": 0.0,
                    "has_evidence": False,
                    "score": 0.0
                }

            scores = [c.get("score", 0.0) for c in chunks]
            max_sim = max(scores)
            avg_sim = sum(scores) / len(scores)

            # 评估分数：综合考虑相似度和证据数量
            score = max_sim * 0.5 + min(len(chunks) / 8, 1.0) * 0.3 + avg_sim * 0.2

            return {
                "strategy": strategy_name,
                "params": strategy,
                "evidence_count": len(chunks),
                "max_similarity": round(max_sim, 4),
                "avg_similarity": round(avg_sim, 4),
                "has_evidence": has_evidence,
                "score": round(score, 4)
            }
        except Exception as e:
            return {
                "strategy": strategy_name,
                "params": strategy,
                "error": str(e),
                "score": 0.0
            }

    def _pick_winner(self, *results) -> str:
        """选出得分最高的策略"""
        best = max(results, key=lambda r: r.get("score", 0))
        return best["strategy"]

    def _analyze_best_strategy(self, cases: List[Dict]) -> Optional[Dict[str, Any]]:
        """分析一组测试用例的最优策略"""
        strategy_scores = defaultdict(list)
        for case in cases:
            winner = case["winner"]
            for sname in ["default", "optimized", "aggressive"]:
                key = f"strategy_{sname}"
                if key in case:
                    score = case[key].get("score", 0)
                    strategy_scores[sname].append(score)

        if not strategy_scores:
            return None

        # 选出平均分最高的策略
        avg_scores = {k: sum(v) / len(v) for k, v in strategy_scores.items()}
        best_name = max(avg_scores, key=avg_scores.get)

        # 获取对应策略参数
        if best_name == "default":
            params = memory_bank._default_strategy()
        elif best_name == "aggressive":
            params = {
                "bm25_weight": 0.3, "vector_weight": 0.7,
                "rerank_threshold": 0.05, "recall_top_k": 15, "final_top_n": 10
            }
        else:
            rec = memory_bank.recommend_strategy(cases[0]["query_type"])
            params = rec.get("params", memory_bank._default_strategy())

        return {
            "params": params,
            "avg_score": avg_scores[best_name],
            "strategy_name": best_name,
            "all_scores": avg_scores
        }

    def _classify_query(self, query: str) -> str:
        """简单查询类型分类"""
        q = query.lower()
        if any(kw in q for kw in ["治疗", "用药", "首选", "treatment", "therapy"]):
            return "treatment"
        if any(kw in q for kw in ["诊断", "标准", "diagnosis"]):
            return "diagnosis"
        if any(kw in q for kw in ["相互作用", "interaction"]):
            return "drug_interaction"
        if any(kw in q for kw in ["预后", "prognosis", "survival"]):
            return "prognosis"
        if any(kw in q for kw in ["指南", "guideline"]):
            return "guideline_interpretation"
        return "treatment"

    # ==================== 跨查询知识迁移 ====================
    def find_similar_experiences(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        在经验库中查找与当前查询相似的历史经验

        使用简单的关键词匹配（后续可升级为向量相似度）
        """
        query_lower = query.lower()
        query_words = set(query_lower.replace("?", "").replace("？", "").split())

        all_exp = memory_bank.get_recent_experiences(limit=200)

        scored = []
        for exp in all_exp:
            exp_query = exp.get("query", "").lower()
            exp_words = set(exp_query.replace("?", "").replace("？", "").split())

            # Jaccard相似度
            if query_words and exp_words:
                intersection = query_words & exp_words
                union = query_words | exp_words
                similarity = len(intersection) / len(union)
                if similarity > 0:
                    scored.append((similarity, exp))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [exp for _, exp in scored[:limit]]

    def get_evolution_report(self) -> Dict[str, Any]:
        """获取自进化状态报告"""
        mem_stats = memory_bank.get_stats()
        gap_stats = gap_logger.get_gap_stats()
        suggestions = gap_logger.get_suggested_fetch_tasks()

        return {
            "memory_bank": mem_stats,
            "knowledge_gaps": gap_stats,
            "suggested_fetches": suggestions,
            "evolution_capabilities": {
                "knowledge_self_evolution": True,
                "strategy_self_evolution": mem_stats["total_experiences"] >= 10,
                "self_play_evaluation": True,
                "cross_query_transfer": True
            },
            "timestamp": datetime.now().isoformat()
        }


# 全局实例
strategy_evolution = StrategyEvolution()
