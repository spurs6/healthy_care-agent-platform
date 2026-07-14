"""
OpenEvidence 临床证据助手 - 知识库管理路由
"""
import os
import shutil
from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from backend.db_store import article_dao, cn_guide_dao, clinical_trial_dao, task_dao, ArticleMeta
from backend.doc_process import doc_processor
from backend.rag_core import rag_retriever, vector_store
from backend.data_collect import scheduler, pubmed_fetcher, europepmc_crawler
from backend.config import CN_GUIDE_DIR, EN_PUBMED_DIR


router = APIRouter()


# ==================== 辅助函数：背景处理任务 ====================
async def process_and_index_document(doc_id: str, file_path: str, meta: ArticleMeta):
    """
    处理和索引文档（背景任务）
    解析PDF → 切分chunk → 写入向量库
    """
    try:
        # 解析PDF并切分
        chunks = doc_processor.process_pdf(file_path, meta)

        # 建立向量索引
        rag_retriever.index_document(chunks)

        print(f"[Admin] 文档处理完成: {doc_id}, 生成 {len(chunks)} 个chunks")

    except Exception as e:
        print(f"[Admin] 文档处理失败 {doc_id}: {e}")


class DocumentInfo(BaseModel):
    """文档信息"""
    doc_id: str
    title: str
    source_type: str
    publish_year: Optional[int]
    evidence_level: str
    language: str
    disease_tags: List[str]


class SearchParams(BaseModel):
    """搜索参数"""
    source_type: Optional[str] = None
    disease: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    evidence_level: Optional[str] = None
    limit: int = 100


# ==================== 文档管理 ====================
@router.get("/documents")
async def list_documents(
    source_type: Optional[str] = None,
    disease: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    evidence_level: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """列出所有文档"""
    articles = article_dao.search(
        source_type=source_type,
        disease=disease,
        year_from=year_from,
        year_to=year_to,
        evidence_level=evidence_level,
        limit=limit,
        offset=offset
    )
    total = article_dao.count_with_filters(
        source_type=source_type,
        disease=disease,
        year_from=year_from,
        year_to=year_to,
        evidence_level=evidence_level
    )
    return {"total": total, "documents": articles}


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    """获取单个文档详情"""
    article = article_dao.get_by_doc_id(doc_id)
    if not article:
        raise HTTPException(status_code=404, detail="文档不存在")
    
    # 如果是中文指南，获取扩展信息
    if article["source_type"] == "cn_guide":
        extra = cn_guide_dao.get_by_doc_id(doc_id)
        if extra:
            article["cn_guide_extra"] = extra
    
    return article


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """删除文档"""
    article = article_dao.get_by_doc_id(doc_id)
    if not article:
        raise HTTPException(status_code=404, detail="文档不存在")
    
    # 删除向量库中的chunks
    rag_retriever.vector_store.delete_by_doc_id(doc_id)
    
    # 删除数据库记录
    article_dao.delete(doc_id)
    
    # 删除PDF文件
    file_path = article.get("file_path", "")
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"[Admin] 删除PDF文件失败 {file_path}: {e}")
    
    return {"message": "文档已删除", "doc_id": doc_id}


# ==================== 文件上传 ====================
@router.post("/upload/cn_guide")
async def upload_cn_guide(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    """上传中文指南PDF"""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="仅支持PDF文件")
    
    # 保存文件
    file_path = os.path.join(CN_GUIDE_DIR, file.filename)
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    # 生成doc_id
    doc_id = f"doc_cn_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # 创建元数据
    meta: ArticleMeta = {
        "doc_id": doc_id,
        "source_type": "cn_guide",
        "title": file.filename,
        "publish_year": datetime.now().year,
        "evidence_level": "1A",
        "language": "zh",
        "disease_tags": [],
        "file_path": file_path,
        "pmid": None,
        "doi": None,
        "abstract": None,
        "keywords": [],
        "authors": [],
        "journal": None,
        "create_time": datetime.now().isoformat(),
        "update_time": datetime.now().isoformat()
    }
    
    article_dao.insert(meta)

    # 后台处理：解析PDF并建立向量索引
    background_tasks.add_task(process_and_index_document, doc_id, file_path, meta)

    return {"message": "文件上传成功，正在后台处理...", "doc_id": doc_id, "file_path": file_path}


@router.post("/upload/en_pubmed")
async def upload_en_pubmed(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    """上传英文文献PDF"""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="仅支持PDF文件")

    file_path = os.path.join(EN_PUBMED_DIR, file.filename)
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    doc_id = f"doc_en_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    meta: ArticleMeta = {
        "doc_id": doc_id,
        "source_type": "pubmed",
        "title": file.filename,
        "publish_year": datetime.now().year,
        "evidence_level": "3B",
        "language": "en",
        "disease_tags": [],
        "file_path": file_path,
        "pmid": None,
        "doi": None,
        "abstract": None,
        "keywords": [],
        "authors": [],
        "journal": None,
        "create_time": datetime.now().isoformat(),
        "update_time": datetime.now().isoformat()
    }

    article_dao.insert(meta)

    # 后台处理：解析PDF并建立向量索引
    if background_tasks:
        background_tasks.add_task(process_and_index_document, doc_id, file_path, meta)

    return {"message": "文件上传成功，正在后台处理...", "doc_id": doc_id, "file_path": file_path}


# ==================== 批量处理 ====================
@router.post("/process/{doc_id}")
async def process_document(doc_id: str):
    """处理单个文档：解析PDF、切分Chunk、建立向量索引"""
    article = article_dao.get_by_doc_id(doc_id)
    if not article:
        raise HTTPException(status_code=404, detail="文档不存在")
    
    file_path = article.get("file_path", "")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=400, detail="PDF文件不存在")
    
    try:
        # 解析PDF并切分
        chunks = doc_processor.process_pdf(file_path, article)
        
        # 建立向量索引
        rag_retriever.index_document(chunks)
        
        return {
            "message": "文档处理完成",
            "doc_id": doc_id,
            "chunks_count": len(chunks)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.post("/batch_process")
async def batch_process_documents(doc_ids: List[str]):
    """批量处理文档"""
    results = {}
    for doc_id in doc_ids:
        try:
            article = article_dao.get_by_doc_id(doc_id)
            if not article:
                results[doc_id] = {"status": "failed", "error": "文档不存在"}
                continue
            
            file_path = article.get("file_path", "")
            if not file_path or not os.path.exists(file_path):
                results[doc_id] = {"status": "failed", "error": "PDF文件不存在"}
                continue
            
            chunks = doc_processor.process_pdf(file_path, article)
            rag_retriever.index_document(chunks)
            
            results[doc_id] = {"status": "success", "chunks_count": len(chunks)}
        except Exception as e:
            results[doc_id] = {"status": "failed", "error": str(e)}
    
    return {"results": results}


# ==================== 增量更新 ====================
@router.post("/incremental/start")
async def start_incremental_update(source: str = "pubmed", days: int = 30):
    """手动触发增量更新"""
    task_id = scheduler.run_manual_update(source=source, days=days)
    return {"message": "增量更新任务已启动", "task_id": task_id}


@router.get("/incremental/status")
async def get_incremental_status(task_type: str = None):
    """获取增量更新任务状态"""
    task = task_dao.get_latest_task(task_type)
    if not task:
        return {"status": "no_task", "message": "暂无任务记录"}
    return task


# ==================== 统计信息 ====================
@router.get("/stats")
async def get_stats():
    """获取知识库统计"""
    db_stats = {
        "total_articles": article_dao.count(),
        "cn_guide": article_dao.count("cn_guide"),
        "pubmed": article_dao.count("pubmed"),
        "cn_eupmc": article_dao.count("cn_eupmc"),
        "europepmc": article_dao.count("europepmc"),
        "pmc_fulltext": article_dao.count("pmc_fulltext"),
        "clinical_trials": clinical_trial_dao.search(limit=1000).__len__()
    }

    vector_stats = vector_store.get_stats()

    return {
        "database": db_stats,
        "vector_store": vector_stats
    }


@router.get("/stats/collections")
async def get_collection_stats():
    """获取向量库各Collection统计"""
    return vector_store.get_stats()


# ==================== 临床试验 ====================
@router.get("/clinical_trials")
async def search_clinical_trials(drug: str = None, disease: str = None, 
                                 min_sample: int = None, limit: int = 100):
    """搜索临床试验数据"""
    trials = clinical_trial_dao.search(
        drug=drug,
        disease=disease,
        min_sample=min_sample,
        limit=limit
    )
    return {"total": len(trials), "trials": trials}