"""
推理原则蒸馏引擎 - Phase 3 推理自进化

功能:
1. 从高分经验中蒸馏可复用的医疗推理原则
2. 按查询类型和疾病领域存储原则
3. 新查询时检索匹配原则指导推理
4. 原则置信度动态更新（贝叶斯式更新）

借鉴EvolveR思路：离线蒸馏 + 在线检索 + 策略强化
"""
import json
import uuid
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import defaultdict

from backend.db_store.database import db_manager
from backend.agent.memory_bank import memory_bank
from backend.config import (
    SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, SILICONFLOW_MODEL
)


class ReasoningEvolution:
    """推理原则蒸馏与检索引擎"""

    def __init__(self):
        self.db = db_manager
        self.min_score_threshold = 0.7
        self.min_samples_for_distillation = 3
        self.confidence_decay = 0.95
        self.confidence_boost = 0.05

    # ==================== 离线蒸馏 ====================
    async def distill_principles(self, query_type: str = None) -> Dict[str, Any]:
        """从高分经验中蒸馏推理原则"""
        import httpx

        if query_type:
            experiences = memory_bank.get_experiences_by_type(query_type, limit=50)
        else:
            experiences = memory_bank.get_recent_experiences(limit=200)

        type_groups = defaultdict(list)
        for exp in experiences:
            score = exp.get("auto_eval_score")
            if score is not None and score >= self.min_score_threshold:
                qtype = exp.get("query_type", "unknown")
                type_groups[qtype].append(exp)

        if not type_groups:
            return {
                "status": "skipped",
                "message": f"无评分>={self.min_score_threshold}的高分经验",
                "distilled_count": 0
            }

        distilled_principles = []
        for qtype, exps in type_groups.items():
            if len(exps) < self.min_samples_for_distillation:
                continue

            exp_summaries = []
            for exp in exps[:10]:
                outcome = exp.get("outcome", {})
                if isinstance(outcome, str):
                    outcome = json.loads(outcome)
                exp_summaries.append({
                    "query": exp.get("query", ""),
                    "strategy": exp.get("strategy", {}),
                    "outcome": {
                        "max_similarity": outcome.get("max_similarity", 0),
                        "evidence_count": outcome.get("evidence_count", 0),
                        "evidence_levels": outcome.get("evidence_levels", []),
                        "gap_detected": outcome.get("gap_detected", False)
                    },
                    "score": exp.get("auto_eval_score", 0)
                })

            prompt = self._build_distillation_prompt(qtype, exp_summaries)

            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(
                        f"{SILICONFLOW_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": SILICONFLOW_MODEL,
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 800,
                            "temperature": 0.3
                        }
                    )

                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"].strip()
                        principles = self._parse_principles(content, qtype, exps)
                        for principle in principles:
                            self._save_principle(principle)
                            distilled_principles.append(principle)
                        print(f"[ReasoningEvolution] {qtype}蒸馏出{len(principles)}条原则")
                    else:
                        print(f"[ReasoningEvolution] {qtype}蒸馏失败: HTTP {resp.status_code}")
            except Exception as e:
                print(f"[ReasoningEvolution] {qtype}蒸馏异常: {e}")
                continue

        return {
            "status": "success",
            "distilled_count": len(distilled_principles),
            "type_coverage": list(type_groups.keys()),
            "principles": [p["principle"][:100] for p in distilled_principles]
        }

    def _build_distillation_prompt(self, query_type: str, experiences: List[Dict]) -> str:
        exp_text = json.dumps(experiences, ensure_ascii=False, indent=2)
        return f"""你是一个医疗AI系统的推理策略分析专家。

以下是{query_type}类型的{len(experiences)}条高分问答经验（评分>=0.7），请分析这些成功案例的共同模式，蒸馏出3-5条可复用的抽象推理原则。

经验数据：
{exp_text}

要求：
1. 原则必须是抽象的、可跨具体病例复用的策略性指导
2. 每条原则用一句话描述，以"当...时，应该..."的格式
3. 涵盖：检索策略、证据选择优先级、回答结构、特殊情况处理
4. 只输出原则列表，每行一条，不要编号和其他内容

示例格式：
当查询涉及合并症时，应该优先检索同时覆盖两种疾病的证据
当证据等级不一致时，应该以最高等级证据为准并标注等级差异
当本地证据相似度低于0.7时，应该触发外部检索补充最新文献"""

    def _parse_principles(self, content: str, query_type: str,
                          source_experiences: List[Dict]) -> List[Dict]:
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        all_diseases = set()
        for exp in source_experiences:
            tags = exp.get("disease_tags", [])
            if isinstance(tags, str):
                tags = json.loads(tags)
            all_diseases.update(tags)

        principles = []
        for line in lines:
            clean = line.lstrip('0123456789.-、） ').strip()
            if len(clean) < 10:
                continue
            principles.append({
                "principle_id": f"prin_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
                "query_type": query_type,
                "disease_tags": list(all_diseases)[:5],
                "principle": clean,
                "source_experiences": [exp.get("exp_id") for exp in source_experiences[:5]],
                "confidence": 0.5
            })
        return principles

    def _save_principle(self, principle: Dict):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO table_reasoning_principle
                (principle_id, query_type, disease_tags, principle,
                 source_experiences, confidence, usage_count, success_count,
                 created_at, updated_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                principle["principle_id"], principle["query_type"],
                json.dumps(principle["disease_tags"], ensure_ascii=False),
                principle["principle"],
                json.dumps(principle["source_experiences"], ensure_ascii=False),
                principle["confidence"], 0, 0,
                datetime.now().isoformat(), datetime.now().isoformat(), "active"
            ))
            conn.commit()

    # ==================== 在线检索 ====================
    def retrieve_principles(self, query_type: str, disease_tags: List[str] = None,
                            limit: int = 5) -> List[Dict[str, Any]]:
        """为新查询检索匹配的推理原则"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM table_reasoning_principle
                WHERE status = 'active' AND query_type = ?
                ORDER BY confidence DESC, usage_count DESC LIMIT ?
            """, (query_type, limit))
            rows = cursor.fetchall()
            principles = [dict(row) for row in rows]

            if disease_tags and principles:
                filtered = []
                for p in principles:
                    p_diseases = json.loads(p.get("disease_tags", "[]")) if p.get("disease_tags") else []
                    if not p_diseases or set(p_diseases) & set(disease_tags):
                        filtered.append(p)
                if filtered:
                    principles = filtered

            for p in principles:
                if p.get("disease_tags"):
                    p["disease_tags"] = json.loads(p["disease_tags"])
                if p.get("source_experiences"):
                    p["source_experiences"] = json.loads(p["source_experiences"])
            return principles

    def format_principles_for_agent(self, principles: List[Dict]) -> str:
        if not principles:
            return ""
        lines = ["\n## 推理原则指导（从历史成功经验蒸馏）\n"]
        for i, p in enumerate(principles):
            confidence = p.get("confidence", 0.5)
            stars = "*" * int(confidence * 5)
            lines.append(f"{i+1}. {p['principle']} (置信度: {confidence:.0%} {stars})")
        return '\n'.join(lines)

    # ==================== 策略强化 ====================
    def update_principle_confidence(self, principle_id: str, success: bool):
        """根据使用结果更新原则置信度"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT confidence, usage_count, success_count FROM table_reasoning_principle WHERE principle_id = ?",
                (principle_id,)
            )
            row = cursor.fetchone()
            if not row:
                return

            old_confidence = row["confidence"]
            usage_count = row["usage_count"] + 1
            success_count = row["success_count"] + (1 if success else 0)
            success_rate = success_count / usage_count
            weight = min(usage_count / 10, 1.0)
            new_confidence = 0.5 * (1 - weight) + success_rate * weight

            if success:
                new_confidence = min(new_confidence + self.confidence_boost, 1.0)
            else:
                new_confidence = max(new_confidence * self.confidence_decay, 0.1)

            cursor.execute("""
                UPDATE table_reasoning_principle
                SET confidence = ?, usage_count = ?, success_count = ?, updated_at = ?
                WHERE principle_id = ?
            """, (round(new_confidence, 4), usage_count, success_count,
                  datetime.now().isoformat(), principle_id))
            conn.commit()

            print(f"[ReasoningEvolution] 原则{principle_id}置信度: {old_confidence:.2f} -> {new_confidence:.2f}")

    # ==================== 统计 ====================
    def get_all_principles(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取所有推理原则列表"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM table_reasoning_principle
                WHERE status = 'active'
                ORDER BY confidence DESC, usage_count DESC LIMIT ?
            """, (limit,))
            rows = [dict(row) for row in cursor.fetchall()]

            for p in rows:
                if p.get("disease_tags"):
                    p["disease_tags"] = json.loads(p["disease_tags"])
                if p.get("source_experiences"):
                    p["source_experiences"] = json.loads(p["source_experiences"])
            return rows

    def get_principle_stats(self) -> Dict[str, Any]:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM table_reasoning_principle WHERE status = 'active'")
            total = cursor.fetchone()[0]

            cursor.execute(
                "SELECT query_type, COUNT(*) as cnt, AVG(confidence) as avg_conf "
                "FROM table_reasoning_principle WHERE status = 'active' GROUP BY query_type"
            )
            type_dist = [
                {"query_type": row["query_type"], "count": row["cnt"],
                 "avg_confidence": round(row["avg_conf"], 4)}
                for row in cursor.fetchall()
            ]

            cursor.execute(
                "SELECT SUM(usage_count), SUM(success_count) FROM table_reasoning_principle WHERE status = 'active'"
            )
            usage_row = cursor.fetchone()
            total_usage = usage_row[0] or 0
            total_success = usage_row[1] or 0

            cursor.execute(
                "SELECT * FROM table_reasoning_principle WHERE status = 'active' ORDER BY confidence DESC LIMIT 10"
            )
            top = [dict(row) for row in cursor.fetchall()]

        return {
            "total_principles": total,
            "type_distribution": type_dist,
            "total_usage": total_usage,
            "total_success": total_success,
            "overall_success_rate": round(total_success / total_usage, 4) if total_usage > 0 else 0.0,
            "top_principles": [
                {"principle_id": p["principle_id"], "query_type": p["query_type"],
                 "principle": p["principle"][:100], "confidence": p["confidence"],
                 "usage_count": p["usage_count"], "success_count": p["success_count"]}
                for p in top
            ]
        }


reasoning_evolution = ReasoningEvolution()
