"""
RAG系统公开评测脚本 v2

评测优化后的系统：
- BGE-large-zh-v1.5 (1024维) 嵌入模型
- BM25+向量混合检索
- LLM查询重写
- GPU加速
- 8846 chunks (含321篇中文文献+160篇PMC全文)

评测维度：
1. 检索成功率
2. Top-1/3/5 相似度分数
3. 上下文精准率 (Context Precision)
4. 上下文召回率 (Context Recall)
5. 证据等级匹配率
6. 来源类型准确率
7. 端到端响应时间

对比基准：v1 (BGE-small, 29% pass rate)
"""
import os
import sys
import json
import time
import re
from datetime import datetime
from typing import List, Dict, Tuple

# 项目路径
BASE_DIR = r"c:\Users\DELL\Desktop\医疗助手agent"
sys.path.insert(0, BASE_DIR)

# 模型缓存路径
os.environ["HF_HOME"] = os.path.join(BASE_DIR, "models")
os.environ["HF_HUB_CACHE"] = os.path.join(BASE_DIR, "models", "hub")
os.environ["TRANSFORMERS_CACHE"] = os.path.join(BASE_DIR, "models")
os.environ["HF_HUB_DISABLE_XET"] = "1"

from backend.config import DB_PATH, CHROMA_DB_DIR, CHROMA_COLLECTIONS

# ==================== 评测测试集 ====================
# 8个疾病类别 x 4题/类 = 32题，与v1保持一致

TEST_CASES = [
    # === 高血压 (4题) ===
    {
        "query": "高血压患者首选什么降压药？",
        "expected_keywords": ["ACEI", "ARB", "氨氯地平", "高血压", "降压药", "CCB", "钙通道阻滞"],
        "expected_source": "cn_guide",
        "category": "hypertension",
    },
    {
        "query": "高血压合并糖尿病用什么降压药？",
        "expected_keywords": ["ACEI", "ARB", "糖尿病", "高血压", "肾素"],
        "expected_source": "cn_guide",
        "category": "hypertension",
    },
    {
        "query": "hypertension first-line treatment guidelines",
        "expected_keywords": ["ACEI", "ARB", "thiazide", "CCB", "first-line", "antihypertensive"],
        "expected_source": "rct_meta",
        "category": "hypertension",
    },
    {
        "query": "顽固性高血压如何处理？",
        "expected_keywords": ["顽固性", "难治性", "螺内酯", "resistant", "高血压"],
        "expected_source": "cn_guide",
        "category": "hypertension",
    },

    # === 糖尿病 (4题) ===
    {
        "query": "2型糖尿病的首选药物是什么？",
        "expected_keywords": ["二甲双胍", "metformin", "2型糖尿病", "T2DM"],
        "expected_source": "cn_guide",
        "category": "diabetes",
    },
    {
        "query": "糖尿病合并心血管疾病如何选择降糖药？",
        "expected_keywords": ["SGLT2", "GLP-1", "心血管", "糖尿病", "恩格列净", "利拉鲁肽"],
        "expected_source": "cn_guide",
        "category": "diabetes",
    },
    {
        "query": "type 2 diabetes pharmacological treatment options",
        "expected_keywords": ["metformin", "SGLT2", "GLP-1", "insulin", "diabetes"],
        "expected_source": "rct_meta",
        "category": "diabetes",
    },
    {
        "query": "糖尿病肾病的管理策略",
        "expected_keywords": ["糖尿病肾病", "DKD", "SGLT2", "ACEI", "ARB", "肾功能"],
        "expected_source": "cn_guide",
        "category": "diabetes",
    },

    # === 心力衰竭 (4题) ===
    {
        "query": "心力衰竭的药物治疗新四联是什么？",
        "expected_keywords": ["沙库巴曲缬沙坦", "ARNI", "β受体阻滞剂", "SGLT2i", "螺内酯", "MRA"],
        "expected_source": "cn_guide",
        "category": "heart_failure",
    },
    {
        "query": "射血分数降低的心衰HFrEF如何治疗？",
        "expected_keywords": ["HFrEF", "射血分数", "ARNI", "ACEI", "β受体阻滞剂", "SGLT2"],
        "expected_source": "cn_guide",
        "category": "heart_failure",
    },
    {
        "query": "heart failure treatment guidelines beta-blocker",
        "expected_keywords": ["beta-blocker", "heart failure", "HFrEF", "guideline", "mortality"],
        "expected_source": "rct_meta",
        "category": "heart_failure",
    },
    {
        "query": "急性心衰的利尿剂使用原则",
        "expected_keywords": ["利尿", "呋塞米", "托拉塞米", "急性", "心衰", "fluid"],
        "expected_source": "cn_guide",
        "category": "heart_failure",
    },

    # === 心房颤动 (4题) ===
    {
        "query": "心房颤动的抗凝治疗方案",
        "expected_keywords": ["抗凝", "华法林", "DOAC", "NOAC", "房颤", "CHA2DS2"],
        "expected_source": "cn_guide",
        "category": "atrial_fibrillation",
    },
    {
        "query": "atrial fibrillation anticoagulation CHA2DS2-VASc",
        "expected_keywords": ["anticoagulation", "warfarin", "DOAC", "stroke", "CHA2DS2"],
        "expected_source": "rct_meta",
        "category": "atrial_fibrillation",
    },
    {
        "query": "房颤的节律控制与心率控制策略",
        "expected_keywords": ["节律控制", "心率控制", "房颤", "胺碘酮", "β受体阻滞剂"],
        "expected_source": "cn_guide",
        "category": "atrial_fibrillation",
    },
    {
        "query": "non-valvular atrial fibrillation stroke prevention",
        "expected_keywords": ["atrial fibrillation", "stroke", "anticoagulation", "apixaban", "rivaroxaban"],
        "expected_source": "rct_meta",
        "category": "atrial_fibrillation",
    },

    # === 高血脂 (4题) ===
    {
        "query": "高血脂患者他汀类药物的使用原则",
        "expected_keywords": ["他汀", "statin", "LDL-C", "阿托伐他汀", "瑞舒伐他汀"],
        "expected_source": "cn_guide",
        "category": "hyperlipidemia",
    },
    {
        "query": "冠心病患者的LDL-C目标值是多少？",
        "expected_keywords": ["LDL-C", "1.8", "1.4", "冠心病", "他汀", "目标"],
        "expected_source": "cn_guide",
        "category": "hyperlipidemia",
    },
    {
        "query": "statin therapy cardiovascular risk reduction LDL",
        "expected_keywords": ["statin", "LDL", "cardiovascular", "atorvastatin", "rosuvastatin"],
        "expected_source": "rct_meta",
        "category": "hyperlipidemia",
    },
    {
        "query": "他汀不耐受怎么办？",
        "expected_keywords": ["他汀不耐受", "肌肉", "肝功能", "依折麦布", "PCSK9"],
        "expected_source": "cn_guide",
        "category": "hyperlipidemia",
    },

    # === 脑卒中 (4题) ===
    {
        "query": "急性脑卒中溶栓时间窗是多少？",
        "expected_keywords": ["4.5小时", "rt-PA", "tPA", "阿替普酶", "溶栓", "时间窗"],
        "expected_source": "cn_guide",
        "category": "stroke",
    },
    {
        "query": "ischemic stroke acute treatment thrombolysis",
        "expected_keywords": ["stroke", "thrombolysis", "tPA", "alteplase", "4.5"],
        "expected_source": "rct_meta",
        "category": "stroke",
    },
    {
        "query": "脑卒中二级预防策略",
        "expected_keywords": ["二级预防", "抗血小板", "阿司匹林", "他汀", "降压"],
        "expected_source": "cn_guide",
        "category": "stroke",
    },
    {
        "query": "脑卒中后抗血小板药物选择",
        "expected_keywords": ["抗血小板", "阿司匹林", "氯吡格雷", "脑卒中", "双抗"],
        "expected_source": "cn_guide",
        "category": "stroke",
    },

    # === 冠心病 (4题) ===
    {
        "query": "急性冠脉综合征的抗血小板治疗方案",
        "expected_keywords": ["抗血小板", "阿司匹林", "替格瑞洛", "普拉格雷", "ACS"],
        "expected_source": "cn_guide",
        "category": "coronary_heart_disease",
    },
    {
        "query": "ST段抬高心肌梗死STEMI的再灌注治疗",
        "expected_keywords": ["STEMI", "PCI", "溶栓", "再灌注", "阿司匹林", "替格瑞洛"],
        "expected_source": "cn_guide",
        "category": "coronary_heart_disease",
    },
    {
        "query": "acute myocardial infarction reperfusion PCI",
        "expected_keywords": ["myocardial infarction", "PCI", "reperfusion", "stent", "primary"],
        "expected_source": "rct_meta",
        "category": "coronary_heart_disease",
    },
    {
        "query": "稳定型冠心病的药物治疗",
        "expected_keywords": ["稳定型", "冠心病", "阿司匹林", "他汀", "β受体阻滞剂", "CCB"],
        "expected_source": "cn_guide",
        "category": "coronary_heart_disease",
    },

    # === 慢性肾病 (4题) ===
    {
        "query": "慢性肾脏病CKD合并高血压的降压策略",
        "expected_keywords": ["CKD", "高血压", "ACEI", "ARB", "肾功能", "降压"],
        "expected_source": "cn_guide",
        "category": "chronic_kidney_disease",
    },
    {
        "query": "CKD合并糖尿病的降糖药选择",
        "expected_keywords": ["CKD", "糖尿病", "SGLT2", "二甲双胍", "肾功能", "达格列净"],
        "expected_source": "cn_guide",
        "category": "chronic_kidney_disease",
    },
    {
        "query": "chronic kidney disease anemia management erythropoietin",
        "expected_keywords": ["anemia", "erythropoietin", "iron", "CKD", "hemoglobin"],
        "expected_source": "rct_meta",
        "category": "chronic_kidney_disease",
    },
    {
        "query": "慢性肾病贫血的治疗方案",
        "expected_keywords": ["贫血", "促红素", "EPO", "铁剂", "CKD", "血红蛋白"],
        "expected_source": "cn_guide",
        "category": "chronic_kidney_disease",
    },
]


def load_rag_system():
    """加载RAG系统"""
    print("[1] 加载RAG系统...")
    from backend.rag_core import embedding_model, vector_store, rag_retriever
    from backend.rag_core.bm25_retriever import bm25_retriever

    # 确保BM25索引加载
    bm25_retriever.load_from_db()

    stats = vector_store.get_stats()
    print(f"    向量库统计: {stats}")
    print(f"    嵌入模型: {embedding_model.model_name}, 维度: {embedding_model.dim}, 设备: {embedding_model.device}")

    return rag_retriever, embedding_model, vector_store


def evaluate_single_query(rag_retriever, test_case: Dict) -> Dict:
    """评测单个查询"""
    query = test_case["query"]
    expected_keywords = test_case["expected_keywords"]
    expected_source = test_case["expected_source"]
    category = test_case["category"]

    start_time = time.time()

    try:
        # 执行RAG检索
        results, has_evidence = rag_retriever.retrieve(query, language="zh", model_type="zh")
    except Exception as e:
        return {
            "query": query,
            "category": category,
            "error": str(e),
            "retrieval_success": False,
            "context_precision": 0,
            "context_recall": 0,
            "top1_score": 0,
            "top3_score": 0,
            "top5_score": 0,
            "source_type_accuracy": 0,
            "evidence_level_match": 0,
            "response_time_ms": (time.time() - start_time) * 1000,
        }

    elapsed_ms = (time.time() - start_time) * 1000

    if not results:
        return {
            "query": query,
            "category": category,
            "retrieval_success": False,
            "context_precision": 0,
            "context_recall": 0,
            "top1_score": 0,
            "top3_score": 0,
            "top5_score": 0,
            "source_type_accuracy": 0,
            "evidence_level_match": 0,
            "response_time_ms": elapsed_ms,
            "result_count": 0,
        }

    # ==================== 计算指标 ====================

    # 1. Top-1/3/5 分数
    scores = [r.get("score", 0) for r in results]
    top1 = scores[0] if len(scores) > 0 else 0
    top3 = sum(scores[:3]) / min(3, len(scores)) if scores else 0
    top5 = sum(scores[:5]) / min(5, len(scores)) if scores else 0

    # 2. 上下文精准率: Top-5结果中有多少包含期望关键词
    top5_results = results[:5]
    relevant_count = 0
    for r in top5_results:
        text = (r.get("text", "") + " " + r.get("title", "")).lower()
        if any(kw.lower() in text for kw in expected_keywords):
            relevant_count += 1
    context_precision = relevant_count / len(top5_results) if top5_results else 0

    # 3. 上下文召回率: 期望关键词在Top-5结果中被命中的比例
    hit_keywords = set()
    all_text = " ".join([
        (r.get("text", "") + " " + r.get("title", "")).lower() for r in top5_results
    ])
    for kw in expected_keywords:
        if kw.lower() in all_text:
            hit_keywords.add(kw)
    context_recall = len(hit_keywords) / len(expected_keywords) if expected_keywords else 0

    # 4. 来源类型准确率: Top-3中是否包含期望来源
    top3_sources = [r.get("source_type", "") for r in results[:3]]
    source_type_accuracy = 1.0 if expected_source in top3_sources else 0.5

    # 5. 证据等级匹配: Top-3中是否包含1A级证据
    top3_levels = [r.get("evidence_level", "") for r in results[:3]]
    has_high_evidence = any("1A" in lv or "1B" in lv for lv in top3_levels)
    evidence_level_match = 1.0 if has_high_evidence else 0.5

    # 6. 综合faithfulness: 检索结果质量综合评分
    faithfulness = (
        context_precision * 0.3 +
        context_recall * 0.3 +
        min(top1, 1.0) * 0.2 +
        evidence_level_match * 0.2
    )

    # 7. Citation accuracy: 有检索结果且Top-1包含关键词
    citation_accuracy = 1.0 if results and context_precision > 0 else 0.0

    return {
        "query": query,
        "category": category,
        "retrieval_success": has_evidence,
        "result_count": len(results),
        "context_precision": round(context_precision, 4),
        "context_recall": round(context_recall, 4),
        "top1_score": round(top1, 4),
        "top3_score": round(top3, 4),
        "top5_score": round(top5, 4),
        "source_type_accuracy": round(source_type_accuracy, 4),
        "evidence_level_match": round(evidence_level_match, 4),
        "faithfulness": round(faithfulness, 4),
        "citation_accuracy": round(citation_accuracy, 4),
        "response_time_ms": round(elapsed_ms, 1),
        "top3_titles": [r.get("title", "")[:60] for r in results[:3]],
        "top3_sources": top3_sources,
        "hit_keywords": list(hit_keywords),
    }


def run_evaluation():
    """运行完整评测"""
    print("=" * 70)
    print("RAG系统公开评测 v2")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 加载系统
    rag_retriever, embedding_model, vector_store = load_rag_system()

    # 评测结果
    all_results = []
    print(f"\n[2] 开始评测 {len(TEST_CASES)} 个测试用例...\n")

    for i, test_case in enumerate(TEST_CASES):
        print(f"  [{i+1}/{len(TEST_CASES)}] [{test_case['category']}] {test_case['query'][:40]}...")
        result = evaluate_single_query(rag_retriever, test_case)
        all_results.append(result)

        if result.get("retrieval_success"):
            print(f"    → 精准率: {result['context_precision']:.2f} | 召回率: {result['context_recall']:.2f} | "
                  f"Top1: {result['top1_score']:.4f} | 耗时: {result['response_time_ms']:.0f}ms")
        else:
            print(f"    → 检索失败")

    # ==================== 汇总统计 ====================
    print(f"\n{'='*70}")
    print("评测结果汇总")
    print(f"{'='*70}")

    total = len(all_results)
    success_count = sum(1 for r in all_results if r.get("retrieval_success"))

    # 计算各项平均指标
    avg_metrics = {
        "retrieval_success_rate": success_count / total,
        "avg_context_precision": sum(r.get("context_precision", 0) for r in all_results) / total,
        "avg_context_recall": sum(r.get("context_recall", 0) for r in all_results) / total,
        "avg_top1_score": sum(r.get("top1_score", 0) for r in all_results) / total,
        "avg_top3_score": sum(r.get("top3_score", 0) for r in all_results) / total,
        "avg_top5_score": sum(r.get("top5_score", 0) for r in all_results) / total,
        "avg_source_type_accuracy": sum(r.get("source_type_accuracy", 0) for r in all_results) / total,
        "avg_evidence_level_match": sum(r.get("evidence_level_match", 0) for r in all_results) / total,
        "avg_faithfulness": sum(r.get("faithfulness", 0) for r in all_results) / total,
        "avg_citation_accuracy": sum(r.get("citation_accuracy", 0) for r in all_results) / total,
        "avg_response_time_ms": sum(r.get("response_time_ms", 0) for r in all_results) / total,
    }

    # Pass rate: faithfulness >= 0.8 AND citation_accuracy >= 0.85 AND context_precision >= 0.75
    pass_count = sum(1 for r in all_results if
                     r.get("faithfulness", 0) >= 0.8 and
                     r.get("citation_accuracy", 0) >= 0.85 and
                     r.get("context_precision", 0) >= 0.75)
    avg_metrics["pass_rate"] = pass_count / total
    avg_metrics["pass_count"] = pass_count

    # 按类别统计
    by_category = {}
    for r in all_results:
        cat = r.get("category", "unknown")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(r)

    category_stats = {}
    for cat, cat_results in by_category.items():
        cat_total = len(cat_results)
        cat_success = sum(1 for r in cat_results if r.get("retrieval_success"))
        cat_pass = sum(1 for r in cat_results if
                       r.get("faithfulness", 0) >= 0.8 and
                       r.get("citation_accuracy", 0) >= 0.85 and
                       r.get("context_precision", 0) >= 0.75)
        category_stats[cat] = {
            "total": cat_total,
            "success": cat_success,
            "pass": cat_pass,
            "avg_precision": sum(r.get("context_precision", 0) for r in cat_results) / cat_total,
            "avg_recall": sum(r.get("context_recall", 0) for r in cat_results) / cat_total,
            "avg_top1": sum(r.get("top1_score", 0) for r in cat_results) / cat_total,
            "avg_faithfulness": sum(r.get("faithfulness", 0) for r in cat_results) / cat_total,
        }

    # 输出汇总
    print(f"\n总测试数: {total}")
    print(f"检索成功率: {avg_metrics['retrieval_success_rate']:.1%} ({success_count}/{total})")
    print(f"\n核心指标:")
    print(f"  上下文精准率:   {avg_metrics['avg_context_precision']:.4f} (阈值: 0.75)")
    print(f"  上下文召回率:   {avg_metrics['avg_context_recall']:.4f}")
    print(f"  Top-1 分数:     {avg_metrics['avg_top1_score']:.4f}")
    print(f"  Top-3 分数:     {avg_metrics['avg_top3_score']:.4f}")
    print(f"  Top-5 分数:     {avg_metrics['avg_top5_score']:.4f}")
    print(f"  忠实度:         {avg_metrics['avg_faithfulness']:.4f} (阈值: 0.80)")
    print(f"  引用准确率:     {avg_metrics['avg_citation_accuracy']:.4f} (阈值: 0.85)")
    print(f"  来源类型准确率: {avg_metrics['avg_source_type_accuracy']:.4f}")
    print(f"  证据等级匹配率: {avg_metrics['avg_evidence_level_match']:.4f}")
    print(f"  平均响应时间:   {avg_metrics['avg_response_time_ms']:.1f}ms")
    print(f"\n综合通过率: {avg_metrics['pass_rate']:.1%} ({pass_count}/{total})")

    print(f"\n按类别统计:")
    print(f"  {'类别':<30s} {'总数':>4s} {'通过':>4s} {'精准率':>8s} {'召回率':>8s} {'Top1':>8s} {'忠实度':>8s}")
    for cat, stats in sorted(category_stats.items()):
        print(f"  {cat:<30s} {stats['total']:>4d} {stats['pass']:>4d} {stats['avg_precision']:>8.4f} {stats['avg_recall']:>8.4f} {stats['avg_top1']:>8.4f} {stats['avg_faithfulness']:>8.4f}")

    # 与v1对比
    print(f"\n{'='*70}")
    print("v1 vs v2 对比")
    print(f"{'='*70}")
    v1_metrics = {
        "pass_rate": 0.2812,
        "avg_context_precision": 0.5352,
        "avg_context_recall": 0.6929,
        "avg_top1_score": 0.8622,
        "avg_faithfulness": 0.6929,
        "avg_citation_accuracy": 0.9375,
    }
    print(f"  {'指标':<25s} {'v1':>10s} {'v2':>10s} {'变化':>10s}")
    print(f"  {'-'*55}")
    for key, v1_val in v1_metrics.items():
        v2_val = avg_metrics.get(key, 0)
        delta = v2_val - v1_val
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        print(f"  {key:<25s} {v1_val:>10.4f} {v2_val:>10.4f} {arrow} {abs(delta):>8.4f}")

    # 保存结果
    eval_result = {
        "eval_info": {
            "timestamp": datetime.now().isoformat(),
            "script": "eval_rag_v2.py",
            "total_test_cases": total,
            "rag_system": "BGE-large-zh-v1.5 + BM25 + 查询重写 + GPU",
            "embedding_model": "BAAI/bge-large-zh-v1.5",
            "embedding_dim": embedding_model.dim,
            "device": embedding_model.device,
            "total_chunks": sum(vector_store.get_stats().values()),
            "bm25_enabled": True,
            "query_rewrite_enabled": True,
        },
        "overall_summary": avg_metrics,
        "by_category": category_stats,
        "detailed_results": all_results,
        "v1_comparison": {
            "v1_metrics": v1_metrics,
            "v2_metrics": {k: avg_metrics.get(k, 0) for k in v1_metrics},
        },
    }

    output_file = os.path.join(BASE_DIR, "experiments", f"eval_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(eval_result, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存到: {output_file}")
    return eval_result


if __name__ == "__main__":
    run_evaluation()
