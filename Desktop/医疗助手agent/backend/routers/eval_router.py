"""
OpenEvidence 临床证据助手 - 自动化评测路由
测试数据必须来自真实来源，不创建任何伪造数据
"""
import os
import json
import uuid
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from backend.config import TEST_SET_DIR, FAITHFULNESS_MIN, CITATION_ACC_MIN, DB_PATH
from backend.rag_core import rag_retriever
from backend.llm_service import llm_service
from backend.evaluation.metrics import (
    calculate_faithfulness, calculate_citation_accuracy,
    calculate_context_precision, calculate_answer_relevance
)
import sqlite3


router = APIRouter()


class TestItem(BaseModel):
    """测试条目 - 必须包含真实问题和标准答案"""
    query: str
    ground_truth: str
    expected_chunks: Optional[List[str]] = None
    source: Optional[str] = None


class EvaluationResult(BaseModel):
    """单题评测结果"""
    query: str
    answer: str
    ground_truth: str
    faithfulness: float
    citation_accuracy: float
    context_precision: float
    answer_relevance: float
    retrieved_chunks: List[str]


class EvaluationReport(BaseModel):
    """评测报告"""
    total_count: int
    avg_faithfulness: float
    avg_citation_accuracy: float
    avg_context_precision: float
    avg_answer_relevance: float
    pass_rate: float
    timestamp: str
    details: List[EvaluationResult]


# ==================== 测试集管理 ====================
@router.get("/test_sets")
async def list_test_sets():
    """列出所有测试集"""
    test_sets = []
    if os.path.exists(TEST_SET_DIR):
        for file in os.listdir(TEST_SET_DIR):
            if file.endswith('.json'):
                file_path = os.path.join(TEST_SET_DIR, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    test_sets.append({
                        "filename": file,
                        "count": len(data),
                        "modified": datetime.fromtimestamp(
                            os.path.getmtime(file_path)
                        ).isoformat()
                    })
                except (json.JSONDecodeError, Exception):
                    pass
    return {"test_sets": test_sets}


@router.post("/test_sets/upload")
async def upload_test_set(file: UploadFile = File(...)):
    """上传测试集"""
    if not file.filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="仅支持JSON文件")
    
    file_path = os.path.join(TEST_SET_DIR, file.filename)
    content = await file.read()
    
    try:
        data = json.loads(content)
        if not isinstance(data, list):
            raise HTTPException(status_code=400, detail="测试集必须是数组格式")
        
        for i, item in enumerate(data):
            if "query" not in item or "ground_truth" not in item:
                raise HTTPException(
                    status_code=400, 
                    detail=f"第{i+1}条数据缺少query或ground_truth字段"
                )
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON格式错误")
    
    with open(file_path, 'wb') as f:
        f.write(content)
    
    return {"message": "测试集上传成功", "filename": file.filename, "count": len(data)}


@router.get("/test_sets/{filename}")
async def get_test_set(filename: str):
    """获取测试集内容"""
    file_path = os.path.join(TEST_SET_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="测试集不存在")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    return {"filename": filename, "items": data, "count": len(data)}


@router.delete("/test_sets/{filename}")
async def delete_test_set(filename: str):
    """删除测试集"""
    file_path = os.path.join(TEST_SET_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="测试集不存在")
    os.remove(file_path)
    return {"message": "测试集已删除", "filename": filename}


# ==================== 基于知识库生成测试集 ====================
@router.post("/test_sets/generate")
async def generate_test_set(num_questions: int = 10):
    """
    基于知识库文档自动生成测试集
    从数据库中随机抽取文献，用LLM生成QA对
    """
    import random
    
    # 从数据库随机抽取文献
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT doc_id, title, abstract, evidence_level, disease_tags 
        FROM table_article_meta 
        WHERE abstract IS NOT NULL AND abstract != ''
        ORDER BY RANDOM() LIMIT ?
    """, (num_questions * 3,))
    articles = cursor.fetchall()
    conn.close()
    
    if len(articles) < 3:
        raise HTTPException(
            status_code=400, 
            detail="知识库中文献不足，至少需要3篇含摘要的文献才能生成测试集"
        )
    
    test_items = []
    for row in articles:
        doc_id, title, abstract, evidence_level, disease_tags = row
        if not abstract or len(abstract) < 50:
            continue
        
        # 用LLM基于文献摘要生成QA对
        prompt = f"""你是一个医学考试出题专家。请基于以下文献信息，生成一道临床问答题及其标准答案。

文献标题：{title}
摘要：{abstract[:800]}
证据等级：{evidence_level or '未知'}
疾病标签：{disease_tags or '未知'}

要求：
1. 问题应该是临床医生可能遇到的实际问题
2. 答案必须完全基于摘要内容，不要编造信息
3. 问题要有明确的医学专业性

请严格按以下JSON格式返回（不要有其他文字）：
{{"query": "问题内容", "ground_truth": "标准答案", "source": "文献标题"}}"""

        try:
            response = await llm_service.llm_client.chat(prompt)
            
            # 解析LLM返回的JSON
            result_text = response.strip()
            if result_text.startswith('```json'):
                result_text = result_text[7:]
            if result_text.startswith('```'):
                result_text = result_text[3:]
            if result_text.endswith('```'):
                result_text = result_text[:-3]
            result_text = result_text.strip()
            
            item = json.loads(result_text)
            if "query" in item and "ground_truth" in item:
                item["expected_chunks"] = None
                test_items.append(item)
                
            if len(test_items) >= num_questions:
                break
                
        except Exception as e:
            print(f"[GenerateTestSet] 生成失败: {e}")
            continue
    
    if not test_items:
        raise HTTPException(
            status_code=500,
            detail="测试集生成失败，LLM未能生成有效的QA对"
        )
    
    # 保存测试集
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"auto_generated_{timestamp}.json"
    file_path = os.path.join(TEST_SET_DIR, filename)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(test_items, f, ensure_ascii=False, indent=2)
    
    return {
        "message": "测试集生成成功",
        "filename": filename,
        "count": len(test_items),
        "items": test_items
    }


# ==================== 评测执行 ====================
@router.post("/run")
async def run_evaluation(filename: str, limit: int = 10):
    """
    运行评测并保存结果到数据库
    """
    file_path = os.path.join(TEST_SET_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"测试集不存在: {filename}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        test_items = json.load(f)
    
    if not test_items:
        raise HTTPException(status_code=400, detail="测试集为空")
    
    test_items = test_items[:limit]
    
    results = []
    total_faithfulness = 0
    total_citation_accuracy = 0
    total_context_precision = 0
    total_answer_relevance = 0
    
    for item in test_items:
        query = item["query"]
        ground_truth = item["ground_truth"]
        
        chunks, has_evidence = rag_retriever.retrieve(query)
        response = await llm_service.answer(query, chunks, has_evidence)
        answer = response["answer"]
        
        faithfulness = calculate_faithfulness(answer, chunks)
        citation_accuracy = calculate_citation_accuracy(answer, chunks)
        context_precision = calculate_context_precision(chunks, item.get("expected_chunks"))
        answer_relevance = calculate_answer_relevance(answer, ground_truth)
        
        result = EvaluationResult(
            query=query,
            answer=answer[:500],
            ground_truth=ground_truth,
            faithfulness=faithfulness,
            citation_accuracy=citation_accuracy,
            context_precision=context_precision,
            answer_relevance=answer_relevance,
            retrieved_chunks=[c.get("doc_id", "") for c in chunks]
        )
        results.append(result)
        
        total_faithfulness += faithfulness
        total_citation_accuracy += citation_accuracy
        total_context_precision += context_precision
        total_answer_relevance += answer_relevance
    
    count = len(results)
    avg_faithfulness = total_faithfulness / count if count > 0 else 0
    avg_citation_accuracy = total_citation_accuracy / count if count > 0 else 0
    avg_context_precision = total_context_precision / count if count > 0 else 0
    avg_answer_relevance = total_answer_relevance / count if count > 0 else 0
    
    pass_count = sum(1 for r in results if 
                     r.faithfulness >= FAITHFULNESS_MIN and 
                     r.citation_accuracy >= CITATION_ACC_MIN)
    pass_rate = pass_count / count if count > 0 else 0
    
    report = EvaluationReport(
        total_count=count,
        avg_faithfulness=avg_faithfulness,
        avg_citation_accuracy=avg_citation_accuracy,
        avg_context_precision=avg_context_precision,
        avg_answer_relevance=avg_answer_relevance,
        pass_rate=pass_rate,
        timestamp=datetime.now().isoformat(),
        details=results
    )
    
    # 保存到数据库
    eval_id = f"eval_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO table_eval_history 
        (eval_id, test_set_filename, total_count, avg_faithfulness, 
         avg_citation_accuracy, avg_context_precision, avg_answer_relevance, 
         pass_rate, details, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        eval_id, filename, count,
        avg_faithfulness, avg_citation_accuracy,
        avg_context_precision, avg_answer_relevance,
        pass_rate,
        json.dumps(report.model_dump(), ensure_ascii=False),
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()
    
    return report


# ==================== 评测历史 ====================
@router.get("/history")
async def get_eval_history(limit: int = 20):
    """获取评测历史记录列表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT eval_id, test_set_filename, total_count, 
               avg_faithfulness, avg_citation_accuracy, 
               avg_context_precision, avg_answer_relevance,
               pass_rate, timestamp
        FROM table_eval_history
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    history = []
    for row in rows:
        history.append({
            "eval_id": row[0],
            "test_set": row[1],
            "total_count": row[2],
            "avg_faithfulness": round(row[3], 3) if row[3] else 0,
            "avg_citation_accuracy": round(row[4], 3) if row[4] else 0,
            "avg_context_precision": round(row[5], 3) if row[5] else 0,
            "avg_answer_relevance": round(row[6], 3) if row[6] else 0,
            "pass_rate": round(row[7], 3) if row[7] else 0,
            "timestamp": row[8]
        })
    
    return {"history": history, "total": len(history)}


@router.get("/history/{eval_id}")
async def get_eval_detail(eval_id: str):
    """获取某次评测的详细结果"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT eval_id, test_set_filename, total_count,
               avg_faithfulness, avg_citation_accuracy,
               avg_context_precision, avg_answer_relevance,
               pass_rate, details, timestamp
        FROM table_eval_history
        WHERE eval_id = ?
    """, (eval_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="评测记录不存在")
    
    details = json.loads(row[8]) if row[8] else {}
    
    return {
        "eval_id": row[0],
        "test_set": row[1],
        "total_count": row[2],
        "avg_faithfulness": round(row[3], 3) if row[3] else 0,
        "avg_citation_accuracy": round(row[4], 3) if row[4] else 0,
        "avg_context_precision": round(row[5], 3) if row[5] else 0,
        "avg_answer_relevance": round(row[6], 3) if row[6] else 0,
        "pass_rate": round(row[7], 3) if row[7] else 0,
        "details": details,
        "timestamp": row[9]
    }


@router.delete("/history/{eval_id}")
async def delete_eval_history(eval_id: str):
    """删除评测历史记录"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM table_eval_history WHERE eval_id = ?", (eval_id,))
    conn.commit()
    conn.close()
    return {"message": "评测记录已删除"}


# ==================== 导出 ====================
@router.post("/export")
async def export_evaluation_report(report: EvaluationReport):
    """导出评测报告"""
    export_path = os.path.join(TEST_SET_DIR, f"eval_report_{datetime.now().strftime('%Y%m%d%H%M%S')}.json")
    
    with open(export_path, 'w', encoding='utf-8') as f:
        json.dump(report.model_dump(), f, ensure_ascii=False)
    
    return {"message": "评测报告已导出", "path": export_path}
