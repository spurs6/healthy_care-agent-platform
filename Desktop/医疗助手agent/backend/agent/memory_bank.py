"""
经验记忆库 - Phase 2 策略自进化核心

功能:
1. 记录每次问答的完整经验（查询类型、策略、结果）
2. 按查询类型检索相似历史经验
3. 推荐最优检索策略
4. 离线分析并更新策略参数
"""
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

from backend.db_store.database import db_manager
from backend.config import SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, SILICONFLOW_MODEL


class MemoryBank:
    """经验记忆库 - 记录、检索、优化"""

    def __init__(self):
        self.db = db_manager

    # ==================== 经验记录 ====================
    def record_experience(self, query: str, query_type: str,
                          disease_tags: List[str], strategy: Dict[str, Any],
                          outcome: Dict[str, Any], tool_calls: List[Dict],
                          answer: str, auto_eval_score: float = None) -> str:
        """
        记录一次完整的问答经验

        Args:
            query: 用户查询
            query_type: 查询类型
            disease_tags: 疾病标签
            strategy: 使用的检索策略
            outcome: 结果指标
            tool_calls: 工具调用记录
            answer: 最终答案
            auto_eval_score: 自动评估分数

        Returns:
            exp_id: 经验记录ID
        """
        exp_id = f"exp_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO table_agent_experience
                (exp_id, query, query_type, disease_tags, strategy, outcome,
                 tool_calls, answer, timestamp, auto_eval_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                exp_id,
                query,
                query_type,
                json.dumps(disease_tags, ensure_ascii=False),
                json.dumps(strategy, ensure_ascii=False),
                json.dumps(outcome, ensure_ascii=False),
                json.dumps(tool_calls, ensure_ascii=False),
                answer[:2000],  # 限制存储长度
                datetime.now().isoformat(),
                auto_eval_score
            ))
            conn.commit()

        print(f"[MemoryBank] 经验已记录: {exp_id} (类型={query_type}, 评分={auto_eval_score})")
        return exp_id

    def get_experience(self, exp_id: str) -> Optional[Dict[str, Any]]:
        """获取单条经验记录"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM table_agent_experience WHERE exp_id = ?",
                (exp_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
        return None

    def get_recent_experiences(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近的经验记录"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM table_agent_experience ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_experiences_by_type(self, query_type: str, limit: int = 50) -> List[Dict[str, Any]]:
        """按查询类型获取经验"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM table_agent_experience WHERE query_type = ? ORDER BY timestamp DESC LIMIT ?",
                (query_type, limit)
            )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    # ==================== 策略推荐 ====================
    def recommend_strategy(self, query_type: str) -> Dict[str, Any]:
        """
        根据历史经验推荐最优检索策略

        Args:
            query_type: 查询类型

        Returns:
            推荐的策略参数
        """
        # 1. 检查是否有优化过的策略
        optimized = self._get_optimized_strategy(query_type)
        if optimized:
            return {
                "source": "optimized",
                "params": optimized,
                "message": f"使用优化策略(基于{optimized.get('sample_count', 0)}次经验)"
            }

        # 2. 从经验记录中计算平均最优策略
        experiences = self.get_experiences_by_type(query_type, limit=20)
        if len(experiences) < 3:
            # 经验不足，返回默认策略
            return {
                "source": "default",
                "params": self._default_strategy(),
                "message": "经验不足，使用默认策略"
            }

        # 3. 分析高分经验，提取共同策略
        scored = []
        for exp in experiences:
            score = exp.get("auto_eval_score")
            if score is not None and score > 0:
                scored.append((score, exp))

        if not scored:
            return {
                "source": "default",
                "params": self._default_strategy(),
                "message": "无评分数据，使用默认策略"
            }

        # 取Top 30%的高分经验
        scored.sort(key=lambda x: x[0], reverse=True)
        top_count = max(3, len(scored) // 3)
        top_experiences = [exp for _, exp in scored[:top_count]]

        # 提取策略参数的平均值
        avg_strategy = self._average_strategy(top_experiences)

        return {
            "source": "experience",
            "params": avg_strategy,
            "message": f"基于{top_count}次高分经验推荐策略",
            "avg_score": sum(s for s, _ in scored[:top_count]) / top_count
        }

    def _default_strategy(self) -> Dict[str, Any]:
        """默认检索策略"""
        return {
            "bm25_weight": 0.4,
            "vector_weight": 0.6,
            "rerank_threshold": 0.1,
            "recall_top_k": 10,
            "final_top_n": 8,
            "use_query_rewrite": True,
            "use_external_search": False
        }

    def _average_strategy(self, experiences: List[Dict[str, Any]]) -> Dict[str, Any]:
        """从多条经验中提取平均策略"""
        strategies = []
        for exp in experiences:
            s = exp.get("strategy", {})
            if isinstance(s, str):
                s = json.loads(s)
            if s:
                strategies.append(s)

        if not strategies:
            return self._default_strategy()

        # 计算数值参数的平均值
        keys = ["bm25_weight", "vector_weight", "rerank_threshold", "recall_top_k", "final_top_n"]
        avg = {}
        for key in keys:
            values = [s.get(key) for s in strategies if s.get(key) is not None]
            if values:
                avg[key] = sum(values) / len(values)
            else:
                avg[key] = self._default_strategy().get(key)

        avg["use_query_rewrite"] = True
        avg["use_external_search"] = any(s.get("use_external_search") for s in strategies)

        return avg

    # ==================== 策略优化 ====================
    def _get_optimized_strategy(self, query_type: str) -> Optional[Dict[str, Any]]:
        """获取已优化的策略"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM table_strategy_optimization WHERE query_type = ? ORDER BY updated_at DESC LIMIT 1",
                (query_type,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "bm25_weight": row["best_bm25_weight"],
                    "vector_weight": row["best_vector_weight"],
                    "rerank_threshold": row["best_rerank_threshold"],
                    "final_top_n": row["best_final_top_n"],
                    "sample_count": row["sample_count"],
                    "avg_score": row["avg_score"]
                }
        return None

    def update_optimized_strategy(self, query_type: str, strategy: Dict[str, Any],
                                  sample_count: int, avg_score: float):
        """更新优化后的策略"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO table_strategy_optimization
                (query_type, best_bm25_weight, best_vector_weight,
                 best_rerank_threshold, best_final_top_n, sample_count, avg_score, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                query_type,
                strategy.get("bm25_weight", 0.4),
                strategy.get("vector_weight", 0.6),
                strategy.get("rerank_threshold", 0.1),
                strategy.get("final_top_n", 8),
                sample_count,
                avg_score,
                datetime.now().isoformat()
            ))
            conn.commit()

        print(f"[MemoryBank] 策略已优化: {query_type} (样本数={sample_count}, 均分={avg_score:.3f})")

    # ==================== 统计分析 ====================
    def get_stats(self) -> Dict[str, Any]:
        """获取记忆库统计信息"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM table_agent_experience")
            total_exp = cursor.fetchone()[0]

            cursor.execute(
                "SELECT query_type, COUNT(*) as cnt FROM table_agent_experience GROUP BY query_type"
            )
            type_dist = {row["query_type"]: row["cnt"] for row in cursor.fetchall()}

            cursor.execute(
                "SELECT AVG(auto_eval_score) FROM table_agent_experience WHERE auto_eval_score IS NOT NULL"
            )
            avg_score = cursor.fetchone()[0] or 0.0

            cursor.execute("SELECT COUNT(*) FROM table_strategy_optimization")
            optimized_count = cursor.fetchone()[0]

            cursor.execute(
                "SELECT query_type, avg_score, sample_count, updated_at FROM table_strategy_optimization"
            )
            optimized_types = [dict(row) for row in cursor.fetchall()]

        return {
            "total_experiences": total_exp,
            "type_distribution": type_dist,
            "avg_eval_score": round(avg_score, 4),
            "optimized_strategy_count": optimized_count,
            "optimized_types": optimized_types
        }

    def _row_to_dict(self, row) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        return {
            "exp_id": row["exp_id"],
            "query": row["query"],
            "query_type": row["query_type"],
            "disease_tags": json.loads(row["disease_tags"]) if row["disease_tags"] else [],
            "strategy": json.loads(row["strategy"]) if row["strategy"] else {},
            "outcome": json.loads(row["outcome"]) if row["outcome"] else {},
            "tool_calls": json.loads(row["tool_calls"]) if row["tool_calls"] else [],
            "answer": row["answer"],
            "timestamp": row["timestamp"],
            "auto_eval_score": row["auto_eval_score"]
        }


# 全局实例
memory_bank = MemoryBank()
