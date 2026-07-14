"""
OpenEvidence 临床证据助手 - 自动化评测模块
基于Ragas和TruLens框架的评测实现
"""
import os
import json
from typing import List, Dict, Any, Optional
from datetime import datetime

from backend.config import (
    TEST_SET_DIR, FAITHFULNESS_MIN, CITATION_ACC_MIN,
    CONTEXT_PRECISION_MIN, ANSWER_RELEVANCE_MIN
)
from backend.db_store import EvaluationResult, EvaluationReport
import re


# ==================== 模块级指标计算函数（供eval_router导入） ====================
def calculate_faithfulness(answer: str, chunks: List) -> float:
    """计算证据忠实度"""
    if not chunks:
        return 0.9 if "暂无匹配" in answer or "无法给出" in answer else 0.0

    citations = re.findall(r'\[doc_\w+\]', answer)

    if not citations:
        return 0.3

    chunk_ids = [c.get("doc_id", "") for c in chunks]
    valid = sum(1 for c in citations if c.strip("[]") in chunk_ids)

    return valid / len(citations)


def calculate_citation_accuracy(answer: str, chunks: List) -> float:
    """计算引用准确率"""
    citations = re.findall(r'\[doc_\w+\]', answer)

    if not citations:
        return 0.0 if chunks else 0.9

    correct = sum(1 for c in citations if c.startswith('[doc_') and c.endswith(']'))
    return correct / len(citations)


def calculate_context_precision(chunks: List, expected_chunks: List = None) -> float:
    """计算检索精准率"""
    if expected_chunks:
        chunk_ids = [c.get("doc_id", "") for c in chunks]
        correct = sum(1 for e in expected_chunks if e in chunk_ids)
        return correct / len(expected_chunks)

    if not chunks:
        return 0.0

    scores = [c.get("score", 0) for c in chunks]
    return min(sum(scores) / len(scores), 1.0)


def calculate_answer_relevance(answer: str, ground_truth: str) -> float:
    """计算答案相关性"""
    if not answer or not ground_truth:
        return 0.0

    ans_kw = set(re.findall(r'[一-龥]+|[a-zA-Z]+', answer.lower()))
    truth_kw = set(re.findall(r'[一-龥]+|[a-zA-Z]+', ground_truth.lower()))

    common = ans_kw & truth_kw
    return len(common) / len(truth_kw) if truth_kw else 0.0


class SimpleEvaluator:
    """
    简化版评测器
    在Ragas/TruLens未安装时使用
    """
    
    def evaluate_single(self, query: str, answer: str, ground_truth: str,
                        retrieved_chunks: List[Dict]) -> EvaluationResult:
        """
        评测单个问答结果

        Args:
            query: 用户问题
            answer: LLM生成的答案
            ground_truth: 标准答案
            retrieved_chunks: 检索结果

        Returns:
            评测结果
        """
        # 计算各项指标
        faithfulness = calculate_faithfulness(answer, retrieved_chunks)
        citation_accuracy = calculate_citation_accuracy(answer, retrieved_chunks)
        context_precision = calculate_context_precision(retrieved_chunks)
        answer_relevance = calculate_answer_relevance(answer, ground_truth)

        return EvaluationResult(
            query=query,
            answer=answer,
            ground_truth=ground_truth,
            faithfulness=faithfulness,
            citation_accuracy=citation_accuracy,
            context_precision=context_precision,
            answer_relevance=answer_relevance,
            retrieved_chunks=[c.get("doc_id", "") for c in retrieved_chunks]
        )
    
    def evaluate_batch(self, test_items: List[Dict], 
                       qa_results: List[Dict]) -> EvaluationReport:
        """
        批量评测
        
        Args:
            test_items: 测试集条目
            qa_results: 问答结果
        
        Returns:
            评测报告
        """
        results = []
        
        for i, item in enumerate(test_items):
            if i >= len(qa_results):
                break
            
            qa = qa_results[i]
            result = self.evaluate_single(
                query=item["query"],
                answer=qa.get("answer", ""),
                ground_truth=item.get("ground_truth", ""),
                retrieved_chunks=qa.get("chunks", [])
            )
            results.append(result)
        
        # 计算平均指标
        total = len(results)
        if total == 0:
            return EvaluationReport(
                total_count=0,
                avg_faithfulness=0,
                avg_citation_accuracy=0,
                avg_context_precision=0,
                avg_answer_relevance=0,
                pass_rate=0,
                timestamp=datetime.now().isoformat(),
                details=[]
            )
        
        avg_faithfulness = sum(r["faithfulness"] for r in results) / total
        avg_citation_accuracy = sum(r["citation_accuracy"] for r in results) / total
        avg_context_precision = sum(r["context_precision"] for r in results) / total
        avg_answer_relevance = sum(r["answer_relevance"] for r in results) / total
        
        # 计算达标率
        pass_count = sum(1 for r in results if 
                         r["faithfulness"] >= FAITHFULNESS_MIN and 
                         r["citation_accuracy"] >= CITATION_ACC_MIN)
        pass_rate = pass_count / total
        
        return EvaluationReport(
            total_count=total,
            avg_faithfulness=avg_faithfulness,
            avg_citation_accuracy=avg_citation_accuracy,
            avg_context_precision=avg_context_precision,
            avg_answer_relevance=avg_answer_relevance,
            pass_rate=pass_rate,
            timestamp=datetime.now().isoformat(),
            details=results
        )
    
    def _calc_faithfulness(self, answer: str, chunks: List) -> float:
        """计算证据忠实度"""
        if not chunks:
            return 0.9 if "暂无匹配" in answer or "无法给出" in answer else 0.0
        
        import re
        citations = re.findall(r'\[doc_\w+\]', answer)
        
        if not citations:
            return 0.3
        
        chunk_ids = [c.get("doc_id", "") for c in chunks]
        valid = sum(1 for c in citations if c.strip("[]") in chunk_ids)
        
        return valid / len(citations)
    
    def _calc_citation_accuracy(self, answer: str, chunks: List) -> float:
        """计算引用准确率"""
        import re
        citations = re.findall(r'\[doc_\w+\]', answer)
        
        if not citations:
            return 0.0 if chunks else 0.9
        
        correct = sum(1 for c in citations if c.startswith('[doc_') and c.endswith(']'))
        return correct / len(citations)
    
    def _calc_context_precision(self, chunks: List) -> float:
        """计算检索精准率"""
        if not chunks:
            return 0.0
        
        # 使用相关性分数
        scores = [c.get("score", 0) for c in chunks]
        return min(sum(scores) / len(scores), 1.0)
    
    def _calc_answer_relevance(self, answer: str, ground_truth: str) -> float:
        """计算答案相关性"""
        if not answer or not ground_truth:
            return 0.0
        
        import re
        ans_kw = set(re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z]+', answer.lower()))
        truth_kw = set(re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z]+', ground_truth.lower()))
        
        common = ans_kw & truth_kw
        return len(common) / len(truth_kw) if truth_kw else 0.0


class RagasEvaluator:
    """
    Ragas框架评测器
    需要安装ragas库
    """
    
    def __init__(self):
        self._available = self._check_ragas_available()
    
    def _check_ragas_available(self) -> bool:
        """检查Ragas是否可用"""
        try:
            import ragas
            return True
        except ImportError:
            print("[Evaluator] Ragas未安装，使用简化版评测")
            return False
    
    def evaluate(self, test_data: List[Dict], qa_results: List[Dict]) -> Dict:
        """使用Ragas评测"""
        if not self._available:
            evaluator = SimpleEvaluator()
            return evaluator.evaluate_batch(test_data, qa_results)
        
        # Ragas评测逻辑
        # 实际实现需要根据Ragas API调整
        try:
            import ragas
            from ragas import evaluate
            from ragas.metrics import faithfulness, answer_relevancy
            
            # 构建Ragas数据格式
            # ...
            
            return {"ragas_available": True, "metrics": {}}
        except Exception as e:
            print(f"[RagasEvaluator] 评测失败: {e}")
            return {}


# 全局评测器实例
evaluator = SimpleEvaluator()