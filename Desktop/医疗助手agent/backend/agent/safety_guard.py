"""
自进化安全防护模块

功能:
1. 错误进化防护 - 统计显著性验证，防止从单次异常学习
2. Human-in-the-loop - 关键变更需要人工确认
3. 版本控制 - 策略和原则变更可回滚
4. 审计日志 - 所有自进化操作留痕
5. 风险评级 - 按风险等级分级处理
"""
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum

from backend.db_store.database import db_manager


class RiskLevel(str, Enum):
    """风险等级"""
    LOW = "low"          # 低风险：经验记录、缺口记录
    MEDIUM = "medium"    # 中风险：策略参数调整
    HIGH = "high"        # 高风险：推理原则变更
    CRITICAL = "critical"  # 极高风险：知识库删除、证据等级变更


class SafetyGuard:
    """自进化安全防护器"""

    def __init__(self):
        self.db = db_manager
        # 安全阈值
        self.min_samples_for_strategy_update = 5   # 策略更新最少需要5次经验
        self.min_samples_for_principle_distill = 3  # 原则蒸馏最少需要3次经验
        self.min_confidence_for_auto_apply = 0.8    # 自动应用原则的最低置信度
        self.max_strategy_change_per_update = 0.3   # 单次策略参数最大变化幅度
        self.significance_threshold = 0.1           # 策略改善的统计显著性阈值

    # ==================== 审计日志 ====================
    def log_evolution_action(self, action_type: str, target_table: str,
                             target_id: str, change_summary: str,
                             old_value: Dict = None, new_value: Dict = None,
                             risk_level: RiskLevel = RiskLevel.LOW,
                             requires_review: bool = False) -> str:
        """
        记录自进化操作审计日志

        Returns:
            audit_id
        """
        audit_id = f"audit_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO table_evolution_audit
                (audit_id, action_type, target_table, target_id, change_summary,
                 old_value, new_value, risk_level, requires_review, reviewed, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                audit_id, action_type, target_table, target_id, change_summary,
                json.dumps(old_value, ensure_ascii=False) if old_value else None,
                json.dumps(new_value, ensure_ascii=False) if new_value else None,
                risk_level.value,
                1 if requires_review else 0,
                0,
                datetime.now().isoformat()
            ))
            conn.commit()

        print(f"[SafetyGuard] 审计日志: {action_type} -> {target_table}/{target_id} (风险={risk_level.value})")
        return audit_id

    # ==================== 策略变更验证 ====================
    def validate_strategy_update(self, query_type: str, old_strategy: Dict,
                                 new_strategy: Dict, sample_count: int) -> Tuple[bool, str]:
        """
        验证策略更新是否安全

        Returns:
            (is_safe, reason)
        """
        # 检查1：样本量是否足够
        if sample_count < self.min_samples_for_strategy_update:
            return False, f"样本量不足: {sample_count} < {self.min_samples_for_strategy_update}"

        # 检查2：参数变化幅度
        for key in ["bm25_weight", "vector_weight", "rerank_threshold"]:
            old_val = old_strategy.get(key, 0)
            new_val = new_strategy.get(key, 0)
            if old_val > 0:
                change_ratio = abs(new_val - old_val) / old_val
                if change_ratio > self.max_strategy_change_per_update:
                    return False, f"{key}变化过大: {old_val:.3f} -> {new_val:.3f} (变化{change_ratio:.1%})"

        # 检查3：权重合法性
        bm25_w = new_strategy.get("bm25_weight", 0.4)
        vec_w = new_strategy.get("vector_weight", 0.6)
        if bm25_w + vec_w < 0.5 or bm25_w + vec_w > 1.5:
            return False, f"权重和不合理: bm25={bm25_w} + vector={vec_w} = {bm25_w+vec_w}"

        return True, "验证通过"

    # ==================== 原则变更验证 ====================
    def validate_principle_distillation(self, source_experiences_count: int,
                                        principles_count: int) -> Tuple[bool, str]:
        """验证原则蒸馏是否安全"""
        if source_experiences_count < self.min_samples_for_principle_distill:
            return False, f"源经验不足: {source_experiences_count} < {self.min_samples_for_principle_distill}"

        if principles_count > 10:
            return False, f"蒸馏原则过多: {principles_count} > 10"

        return True, "验证通过"

    def validate_principle_application(self, confidence: float) -> Tuple[bool, str]:
        """验证原则是否可以自动应用"""
        if confidence < self.min_confidence_for_auto_apply:
            return False, f"置信度不足: {confidence:.2f} < {self.min_confidence_for_auto_apply}"
        return True, "验证通过"

    # ==================== 统计显著性检验 ====================
    def check_statistical_significance(self, old_scores: List[float],
                                       new_scores: List[float]) -> Tuple[bool, float, str]:
        """
        检查策略改善是否具有统计显著性

        Returns:
            (is_significant, effect_size, description)
        """
        if len(old_scores) < 3 or len(new_scores) < 3:
            return False, 0.0, "样本量不足，无法判断显著性"

        old_mean = sum(old_scores) / len(old_scores)
        new_mean = sum(new_scores) / len(new_scores)
        effect_size = new_mean - old_mean

        # 简单的效应量检验（Cohen's d近似）
        old_var = sum((x - old_mean) ** 2 for x in old_scores) / len(old_scores)
        new_var = sum((x - new_mean) ** 2 for x in new_scores) / len(new_scores)
        pooled_std = (old_var + new_var) ** 0.5

        if pooled_std == 0:
            return effect_size > 0, effect_size, "无方差，直接比较均值"

        cohens_d = effect_size / pooled_std

        if abs(cohens_d) < 0.2:
            return False, effect_size, f"效应量过小(Cohen's d={cohens_d:.3f})，不具备统计显著性"
        elif effect_size > 0:
            return True, effect_size, f"改善显著(Cohen's d={cohens_d:.3f})，效应量={effect_size:.4f}"
        else:
            return False, effect_size, f"策略退化(Cohen's d={cohens_d:.3f})，不应更新"

    # ==================== 审计查询 ====================
    def get_audit_logs(self, limit: int = 50,
                       risk_level: str = None,
                       unreviewed_only: bool = False) -> List[Dict]:
        """获取审计日志"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            sql = "SELECT * FROM table_evolution_audit WHERE 1=1"
            params = []

            if risk_level:
                sql += " AND risk_level = ?"
                params.append(risk_level)

            if unreviewed_only:
                sql += " AND requires_review = 1 AND reviewed = 0"

            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)
            logs = [dict(row) for row in cursor.fetchall()]

            for log in logs:
                if log.get("old_value"):
                    log["old_value"] = json.loads(log["old_value"])
                if log.get("new_value"):
                    log["new_value"] = json.loads(log["new_value"])

            return logs

    def review_audit_log(self, audit_id: str, reviewer: str,
                         approved: bool, note: str = ""):
        """审核一条审计日志"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE table_evolution_audit
                SET reviewed = 1, reviewer = ?, review_note = ?
                WHERE audit_id = ?
            """, (reviewer, f"{'APPROVED' if approved else 'REJECTED'}: {note}", audit_id))
            conn.commit()

        print(f"[SafetyGuard] 审计日志{audit_id}已审核: {'通过' if approved else '拒绝'}")

    def get_safety_stats(self) -> Dict[str, Any]:
        """获取安全统计"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM table_evolution_audit")
            total = cursor.fetchone()[0]

            cursor.execute(
                "SELECT risk_level, COUNT(*) as cnt FROM table_evolution_audit GROUP BY risk_level"
            )
            risk_dist = {row["risk_level"]: row["cnt"] for row in cursor.fetchall()}

            cursor.execute(
                "SELECT COUNT(*) FROM table_evolution_audit WHERE requires_review = 1 AND reviewed = 0"
            )
            pending_review = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM table_evolution_audit WHERE reviewed = 1"
            )
            reviewed = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM table_evolution_audit WHERE requires_review = 0"
            )
            auto_approved = cursor.fetchone()[0]

        return {
            "total_actions": total,
            "risk_distribution": risk_dist,
            "pending_review": pending_review,
            "reviewed": reviewed,
            "auto_approved": auto_approved,
            "safety_thresholds": {
                "min_samples_for_strategy": self.min_samples_for_strategy_update,
                "min_samples_for_principle": self.min_samples_for_principle_distill,
                "min_confidence_for_auto_apply": self.min_confidence_for_auto_apply,
                "max_strategy_change_per_update": self.max_strategy_change_per_update,
                "significance_threshold": self.significance_threshold
            }
        }


# 全局实例
safety_guard = SafetyGuard()
