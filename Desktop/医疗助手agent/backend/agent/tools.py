"""
Agent工具定义 - LangChain Tool Decorators

工具清单:
1. local_search       - 搜索本地知识库
2. external_search    - 实时搜索PubMed+EuropePMC
3. evidence_evaluator - 评估证据质量
4. query_classifier   - 分类查询类型
"""
import json
from typing import Annotated
from langchain_core.tools import tool

from backend.rag_core import rag_retriever
from backend.agent.external_search import external_searcher


@tool
def local_search(query: str) -> str:
    """
    搜索本地医疗知识库，返回相关的临床循证证据片段。
    本地知识库包含中文临床指南、PubMed英文文献、EuropePMC中文文献。
    这是首选的检索工具，应首先调用。

    Args:
        query: 用户的医疗问题或搜索关键词
    """
    chunks, has_evidence = rag_retriever.retrieve(query)

    if not chunks:
        return json.dumps({
            "status": "no_result",
            "message": "本地知识库未检索到相关证据",
            "max_similarity": 0.0,
            "evidence_count": 0
        }, ensure_ascii=False)

    # 格式化结果
    formatted = []
    max_score = 0.0
    for i, chunk in enumerate(chunks[:8]):
        score = chunk.get("score", 0.0)
        max_score = max(max_score, score)
        formatted.append({
            "rank": i + 1,
            "doc_id": chunk.get("doc_id", ""),
            "title": chunk.get("title", ""),
            "score": round(score, 4),
            "evidence_level": chunk.get("evidence_level", ""),
            "source_type": chunk.get("source_type", ""),
            "text_preview": chunk.get("text", "")[:300]
        })

    gap_detected = max_score < 0.7

    return json.dumps({
        "status": "success",
        "message": f"检索到{len(chunks)}条证据，最高相似度{max_score:.4f}",
        "max_similarity": round(max_score, 4),
        "evidence_count": len(chunks),
        "gap_detected": gap_detected,
        "gap_reason": "最高相似度低于0.7，建议补充外部检索" if gap_detected else None,
        "evidence": formatted
    }, ensure_ascii=False)


@tool
def external_search(query: str) -> str:
    """
    实时搜索PubMed和EuropePMC获取最新医学文献。
    当本地知识库检索结果不足（相似度低或无结果）时调用此工具。
    支持中英文搜索，会自动去重合并两个源的结果。

    Args:
        query: 搜索关键词（英文搜索词在PubMed上效果更好）
    """
    result = external_searcher.search_both(query, max_results=5)

    articles = result.get("articles", [])
    if not articles:
        return json.dumps({
            "status": "no_result",
            "message": "外部检索未找到相关文献",
            "total": 0
        }, ensure_ascii=False)

    # 格式化结果
    formatted = []
    for i, article in enumerate(articles):
        formatted.append({
            "rank": i + 1,
            "doc_id": article.get("doc_id", ""),
            "source": article.get("source", ""),
            "pmid": article.get("pmid", ""),
            "title": article.get("title", ""),
            "journal": article.get("journal", ""),
            "publish_year": article.get("publish_year"),
            "evidence_level": article.get("evidence_level", ""),
            "abstract_preview": article.get("abstract", "")[:400]
        })

    # 异步保存到数据库（不阻塞当前请求）
    try:
        external_searcher.save_to_database(articles)
    except Exception as e:
        print(f"[Tool:external_search] 保存到数据库失败: {e}")

    return json.dumps({
        "status": "success",
        "message": f"外部检索到{len(articles)}篇文献",
        "total": len(articles),
        "sources": result.get("sources", {}),
        "evidence": formatted
    }, ensure_ascii=False)


@tool
def evidence_evaluator(evidence_summary: str, user_query: str) -> str:
    """
    评估检索到的证据是否足够回答用户的临床问题。
    在所有检索完成后、生成答案前调用此工具。

    Args:
        evidence_summary: 目前收集到的所有证据的简要摘要（包括来源、数量、最高相似度等）
        user_query: 用户的原始临床问题
    """
    # 简单的规则评估
    evidence_lower = evidence_summary.lower()

    # 评估维度
    has_guideline = any(kw in evidence_lower for kw in ["指南", "guideline", "cn_guide"])
    has_rct = any(kw in evidence_lower for kw in ["rct", "randomized", "随机对照"])
    has_meta = any(kw in evidence_lower for kw in ["meta", "systematic review", "荟萃"])
    evidence_count = evidence_summary.count("doc_") + evidence_summary.count("ext_")

    score = 0.0
    reasons = []

    if has_guideline:
        score += 0.3
        reasons.append("包含临床指南证据(+0.3)")
    if has_rct:
        score += 0.25
        reasons.append("包含RCT证据(+0.25)")
    if has_meta:
        score += 0.25
        reasons.append("包含Meta分析证据(+0.25)")
    if evidence_count >= 3:
        score += 0.2
        reasons.append(f"证据数量充足({evidence_count}条, +0.2)")
    elif evidence_count >= 1:
        score += 0.1
        reasons.append(f"证据数量较少({evidence_count}条, +0.1)")
    else:
        reasons.append("无有效证据(0)")

    sufficient = score >= 0.5
    recommendation = "证据充分，可以生成答案" if sufficient else "证据不足，建议继续检索或使用external_search补充"

    return json.dumps({
        "status": "evaluated",
        "message": recommendation,
        "sufficient": sufficient,
        "score": round(score, 2),
        "evidence_count": evidence_count,
        "has_guideline": has_guideline,
        "has_rct": has_rct,
        "has_meta": has_meta,
        "reasons": reasons,
        "recommendation": recommendation
    }, ensure_ascii=False)


@tool
def query_classifier(query: str) -> str:
    """
    分类用户的临床问题类型，用于选择最优检索策略。
    支持的类别：treatment(治疗推荐), diagnosis(诊断标准),
    drug_interaction(药物相互作用), prognosis(预后评估),
    guideline_interpretation(指南解读), mechanism(机制原理)

    Args:
        query: 用户的临床问题
    """
    query_lower = query.lower()

    # 关键词规则分类
    rules = {
        "treatment": ["治疗", "用药", "首选", "推荐", "方案", "treatment", "therapy", "first-line", "药物选择"],
        "diagnosis": ["诊断", "标准", " criteria", "diagnosis", "筛查", "screening", "指标"],
        "drug_interaction": ["相互作用", "联用", "合用", "禁忌", "interaction", "combination", "contraindication"],
        "prognosis": ["预后", "生存率", "死亡率", "prognosis", "survival", "mortality", "结局"],
        "guideline_interpretation": ["指南", "推荐意见", "guideline", "recommendation", "更新"],
        "mechanism": ["机制", "原理", "作用", "mechanism", "pathophysiology", "药理"]
    }

    scores = {}
    for qtype, keywords in rules.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            scores[qtype] = score

    if scores:
        best_type = max(scores, key=scores.get)
    else:
        best_type = "treatment"  # 默认

    # 疾病领域识别
    disease_map = {
        "高血压": ["高血压", "hypertension", "血压", "blood pressure"],
        "糖尿病": ["糖尿病", "diabetes", "血糖", "glucose"],
        "高血脂": ["高血脂", "hyperlipidemia", "血脂", "cholesterol", "LDL"],
        "冠心病": ["冠心病", "coronary", "心肌缺血", "心绞痛"],
        "心力衰竭": ["心力衰竭", "心衰", "heart failure"],
        "心房颤动": ["房颤", "心房颤动", "atrial fibrillation"],
        "脑卒中": ["脑卒中", "中风", "stroke"],
        "肾病": ["肾病", "kidney", "CKD", "肾功能"]
    }

    diseases = []
    for disease, keywords in disease_map.items():
        if any(kw in query_lower for kw in keywords):
            diseases.append(disease)

    message = f"问题分类为：{best_type}，识别疾病：{', '.join(diseases) if diseases else '无'}"

    return json.dumps({
        "message": message,
        "query_type": best_type,
        "confidence": scores.get(best_type, 0) / max(sum(scores.values()), 1),
        "diseases": diseases,
        "all_scores": scores
    }, ensure_ascii=False)


# 工具列表（供Agent使用）
ALL_TOOLS = [local_search, external_search, evidence_evaluator, query_classifier]
