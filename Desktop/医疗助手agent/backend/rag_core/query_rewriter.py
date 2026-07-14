"""
查询重写模块 - 使用LLM扩展查询以提升召回率

功能：
1. 同义词扩展（如"高血压" → "hypertension", "血压升高"）
2. 中英文双语查询生成
3. 关键医学实体提取
"""
import os
import re
import json
from typing import List, Tuple

from backend.config import (
    SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, SILICONFLOW_MODEL,
    ENABLE_TRANSFORMER_EMBEDDINGS
)


# 预定义的医学同义词映射（无需LLM，快速匹配）
MEDICAL_SYNONYMS = {
    # 高血压
    "高血压": ["hypertension", "high blood pressure", "血压升高", "降压"],
    "hypertension": ["高血压", "high blood pressure", "血压升高"],
    # 糖尿病
    "糖尿病": ["diabetes", "diabetes mellitus", "血糖升高", "降糖"],
    "diabetes": ["糖尿病", "diabetes mellitus", "血糖升高"],
    "2型糖尿病": ["type 2 diabetes", "T2DM", "2型糖尿病"],
    # 心力衰竭
    "心力衰竭": ["heart failure", "心衰", "HF", "心功能不全"],
    "heart failure": ["心力衰竭", "心衰", "心功能不全"],
    # 心房颤动
    "心房颤动": ["atrial fibrillation", "房颤", "AF", "心房纤颤"],
    "atrial fibrillation": ["心房颤动", "房颤", "心房纤颤"],
    # 高血脂
    "高血脂": ["hyperlipidemia", "血脂异常", "降脂", "cholesterol"],
    "hyperlipidemia": ["高血脂", "血脂异常", "降脂"],
    # 脑卒中
    "脑卒中": ["stroke", "中风", "脑血管意外", "cerebrovascular"],
    "stroke": ["脑卒中", "中风", "脑血管意外"],
    # 冠心病
    "冠心病": ["coronary heart disease", "CHD", "冠状动脉疾病", "心肌缺血"],
    "coronary": ["冠心病", "冠状动脉疾病", "CHD"],
    # 肾病
    "肾病": ["kidney disease", "chronic kidney disease", "CKD", "肾功能不全"],
    "CKD": ["慢性肾脏病", "chronic kidney disease", "肾功能不全"],
    # 治疗相关
    "药物治疗": ["pharmacotherapy", "drug treatment", "medication", "用药"],
    "治疗": ["treatment", "therapy", "management", "干预"],
    "诊断": ["diagnosis", "diagnostic criteria", "诊断标准"],
    "预防": ["prevention", "prophylaxis", "一级预防", "二级预防"],
    # 药物类
    "降压药": ["antihypertensive drugs", "antihypertensive agents", "降压药物"],
    "降糖药": ["antidiabetic drugs", "hypoglycemic agents", "降糖药物"],
    "他汀": ["statins", "statin therapy", "他汀类药物"],
    "ACEI": ["ACE inhibitor", "血管紧张素转换酶抑制剂"],
    "ARB": ["angiotensin receptor blocker", "血管紧张素受体拮抗剂"],
    "β受体阻滞剂": ["beta-blocker", "beta blocker", "β-blocker"],
}


class QueryRewriter:
    """查询重写器"""

    def __init__(self):
        self.llm_available = bool(SILICONFLOW_API_KEY)

    def rewrite(self, query: str) -> Tuple[str, List[str]]:
        """重写查询，返回（增强查询, 扩展查询列表）

        Args:
            query: 原始查询

        Returns:
            (enhanced_query, expanded_queries)
            - enhanced_query: 融合了同义词的增强查询
            - expanded_queries: 用于多路召回的扩展查询列表
        """
        # Step 1: 基于预定义同义词表的快速扩展
        synonyms_found = set()
        expanded_queries = []

        query_lower = query.lower()
        for key, synonyms in MEDICAL_SYNONYMS.items():
            if key.lower() in query_lower:
                synonyms_found.update(synonyms)

        # 构建增强查询：原始查询 + 同义词
        if synonyms_found:
            synonym_text = " ".join(synonyms_found)
            enhanced_query = f"{query} {synonym_text}"
            # 创建扩展查询用于多路召回
            expanded_queries.append(query)  # 原始查询
            # 中英文双语查询
            en_synonyms = [s for s in synonyms_found if re.match(r'^[a-zA-Z]', s)]
            zh_synonyms = [s for s in synonyms_found if re.match(r'^[\u4e00-\u9fff]', s)]
            if en_synonyms and re.search(r'[\u4e00-\u9fff]', query):
                # 中文查询 + 英文同义词查询
                expanded_queries.append(" ".join(en_synonyms[:5]))
            if zh_synonyms and re.search(r'[a-zA-Z]{3,}', query):
                # 英文查询 + 中文同义词查询
                expanded_queries.append(" ".join(zh_synonyms[:5]))
        else:
            enhanced_query = query
            expanded_queries = [query]

        # Step 2: LLM查询重写（如果可用且查询较短）
        if self.llm_available and len(query) < 100:
            llm_expansions = self._llm_rewrite(query)
            if llm_expansions:
                expanded_queries.extend(llm_expansions)

        # 去重
        seen = set()
        unique_queries = []
        for q in expanded_queries:
            if q not in seen and q.strip():
                seen.add(q)
                unique_queries.append(q)

        return enhanced_query, unique_queries[:5]  # 最多5个扩展查询

    def _llm_rewrite(self, query: str) -> List[str]:
        """使用LLM重写查询（可选，失败时静默跳过）"""
        try:
            import requests

            prompt = f"""你是一个医学文献检索查询重写助手。请将以下用户查询重写为3个不同的检索查询，以提高检索召回率：

原始查询：{query}

要求：
1. 生成中英文双语版本
2. 包含医学术语和通用表述两种形式
3. 每行一个查询，不要编号

输出格式（直接输出3行查询，不要其他内容）："""

            headers = {
                "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": SILICONFLOW_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0.3,
            }

            resp = requests.post(
                f"{SILICONFLOW_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
                timeout=10,
            )

            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"].strip()
                lines = [line.strip() for line in content.split("\n") if line.strip()]
                return lines[:3]  # 最多3个LLM扩展
        except Exception as e:
            print(f"[QueryRewriter] LLM重写失败（不影响检索）: {e}")

        return []


# 全局实例
query_rewriter = QueryRewriter()
