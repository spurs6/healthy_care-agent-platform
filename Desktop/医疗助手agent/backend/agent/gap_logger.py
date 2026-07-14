"""
知识缺口记录器 - Phase 2 知识自进化

功能:
1. 记录每次检索不足的知识缺口
2. 分析缺口模式（高频缺口领域）
3. 触发自动补充（批量爬取）
4. 追踪缺口解决状态
"""
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import Counter

from backend.db_store.database import db_manager


class GapLogger:
    """知识缺口记录与分析"""

    def __init__(self):
        self.db = db_manager

    # ==================== 缺口记录 ====================
    def log_gap(self, query: str, gap_type: str, max_similarity: float,
                domain: str = "", external_source: str = "",
                external_results_count: int = 0,
                fetched_articles: List[str] = None) -> str:
        """
        记录一个知识缺口

        Args:
            query: 触发缺口的查询
            gap_type: 缺口类型 (no_result / low_similarity / outdated)
            max_similarity: 本地检索的最高相似度
            domain: 疾病领域
            external_source: 外部补充来源 (pubmed / europepmc / both)
            external_results_count: 外部检索到的文献数
            fetched_articles: 获取到的文章ID列表

        Returns:
            gap_id: 缺口记录ID
        """
        gap_id = f"gap_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO table_knowledge_gap
                (gap_id, query, gap_type, max_similarity, domain,
                 external_source, external_results_count, fetched_articles,
                 resolved, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                gap_id,
                query,
                gap_type,
                max_similarity,
                domain,
                external_source,
                external_results_count,
                json.dumps(fetched_articles or [], ensure_ascii=False),
                1 if external_results_count > 0 else 0,  # 有外部结果则标记为已解决
                datetime.now().isoformat()
            ))
            conn.commit()

        print(f"[GapLogger] 缺口已记录: {gap_id} (类型={gap_type}, 领域={domain}, 外部补充={external_results_count}篇)")
        return gap_id

    # ==================== 缺口分析 ====================
    def get_gap_stats(self) -> Dict[str, Any]:
        """获取缺口统计"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM table_knowledge_gap")
            total = cursor.fetchone()[0]

            cursor.execute(
                "SELECT gap_type, COUNT(*) as cnt FROM table_knowledge_gap GROUP BY gap_type"
            )
            type_dist = {row["gap_type"]: row["cnt"] for row in cursor.fetchall()}

            cursor.execute(
                "SELECT domain, COUNT(*) as cnt FROM table_knowledge_gap WHERE domain != '' GROUP BY domain ORDER BY cnt DESC LIMIT 10"
            )
            domain_dist = {row["domain"]: row["cnt"] for row in cursor.fetchall()}

            cursor.execute(
                "SELECT COUNT(*) FROM table_knowledge_gap WHERE resolved = 1"
            )
            resolved = cursor.fetchone()[0]

            cursor.execute(
                "SELECT AVG(max_similarity) FROM table_knowledge_gap"
            )
            avg_sim = cursor.fetchone()[0] or 0.0

        return {
            "total_gaps": total,
            "type_distribution": type_dist,
            "domain_distribution": domain_dist,
            "resolved_count": resolved,
            "resolution_rate": round(resolved / total, 4) if total > 0 else 0.0,
            "avg_max_similarity": round(avg_sim, 4)
        }

    def get_high_frequency_gaps(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取高频缺口领域，用于批量补充

        Returns:
            高频缺口列表，按出现次数排序
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT domain, COUNT(*) as freq,
                       AVG(max_similarity) as avg_sim,
                       MAX(timestamp) as last_seen
                FROM table_knowledge_gap
                WHERE resolved = 0 AND domain != ''
                GROUP BY domain
                HAVING freq >= 2
                ORDER BY freq DESC
                LIMIT ?
            """, (limit,))

            return [dict(row) for row in cursor.fetchall()]

    def get_recent_gaps(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近的缺口记录"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM table_knowledge_gap ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def mark_resolved(self, gap_id: str):
        """标记缺口为已解决"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE table_knowledge_gap SET resolved = 1 WHERE gap_id = ?",
                (gap_id,)
            )
            conn.commit()

    def get_unresolved_count(self) -> int:
        """获取未解决缺口数"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM table_knowledge_gap WHERE resolved = 0")
            return cursor.fetchone()[0]

    def get_suggested_fetch_tasks(self) -> List[Dict[str, Any]]:
        """
        基于缺口模式生成建议的批量获取任务
        """
        high_freq = self.get_high_frequency_gaps(limit=5)
        suggestions = []

        for gap in high_freq:
            domain = gap["domain"]
            freq = gap["freq"]
            avg_sim = gap["avg_sim"]

            # 根据领域和频率生成搜索词
            search_terms = self._generate_search_terms(domain)

            suggestions.append({
                "domain": domain,
                "gap_frequency": freq,
                "avg_similarity": round(avg_sim, 4),
                "suggested_search_terms": search_terms,
                "priority": "high" if freq >= 5 else "medium",
                "estimated_articles": freq * 5
            })

        return suggestions

    def _generate_search_terms(self, domain: str) -> List[str]:
        """根据领域生成搜索词"""
        term_map = {
            "高血压": ["hypertension treatment guideline", "高血压 治疗 指南", "antihypertensive drug"],
            "糖尿病": ["type 2 diabetes treatment", "糖尿病 治疗", "diabetes medication"],
            "高血脂": ["hyperlipidemia treatment", "高血脂 他汀", "lipid lowering therapy"],
            "冠心病": ["coronary heart disease treatment", "冠心病 治疗", "CHD management"],
            "心力衰竭": ["heart failure treatment", "心力衰竭 治疗", "HFrEF therapy"],
            "心房颤动": ["atrial fibrillation management", "房颤 抗凝", "AF anticoagulation"],
            "脑卒中": ["stroke treatment", "脑卒中 治疗", "stroke prevention"],
            "肾病": ["chronic kidney disease treatment", "慢性肾病 治疗", "CKD management"]
        }
        return term_map.get(domain, [domain, f"{domain} treatment"])


# 全局实例
gap_logger = GapLogger()
