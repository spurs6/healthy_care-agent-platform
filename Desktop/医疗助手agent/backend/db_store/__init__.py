"""
OpenEvidence 临床证据助手 - 数据存储模块
"""
from backend.db_store.database import (
    db_manager, article_dao, cn_guide_dao, clinical_trial_dao, task_dao,
    DatabaseManager, ArticleDAO, CnGuideDAO, ClinicalTrialDAO, TaskDAO
)
from backend.db_store.models import (
    ArticleMeta, CnGuideExtra, ClinicalTrial, ChunkMeta,
    ChatRequest, ChatResponse, RetrievedChunk,
    EvaluationResult, EvaluationReport,
    DocumentUpload, IncrementalTask
)

__all__ = [
    # 数据库管理器
    "db_manager", "DatabaseManager",
    # DAO层
    "article_dao", "ArticleDAO",
    "cn_guide_dao", "CnGuideDAO",
    "clinical_trial_dao", "ClinicalTrialDAO",
    "task_dao", "TaskDAO",
    # 数据模型
    "ArticleMeta", "CnGuideExtra", "ClinicalTrial", "ChunkMeta",
    "ChatRequest", "ChatResponse", "RetrievedChunk",
    "EvaluationResult", "EvaluationReport",
    "DocumentUpload", "IncrementalTask"
]