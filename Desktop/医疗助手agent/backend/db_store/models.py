"""
OpenEvidence 临床证据助手 - 数据模型定义
所有医学元数据、Chunk结构使用TypedDict强类型约束
"""
from typing import TypedDict, List, Optional, Literal
from datetime import datetime


# ==================== 文献元数据模型 ====================
class ArticleMeta(TypedDict):
    """通用文献元数据表模型 - table_article_meta"""
    doc_id: str  # 全局唯一文档ID，如 doc_cn_0036, doc_en_0125
    source_type: Literal["pubmed", "cn_guide", "ctgov"]  # 来源类型
    title: str  # 文档标题
    publish_year: int  # 发布年份
    evidence_level: str  # 循证等级：1A/ⅠA、2B/ⅡB等
    language: Literal["zh", "en"]  # 语言
    disease_tags: List[str]  # 疾病标签数组
    file_path: str  # 本地PDF存储路径
    pmid: Optional[str]  # PubMed ID（英文文献）
    doi: Optional[str]  # DOI号
    abstract: Optional[str]  # 摘要
    keywords: Optional[List[str]]  # 关键词
    authors: Optional[List[str]]  # 作者列表
    journal: Optional[str]  # 期刊名称
    create_time: Optional[str]  # 入库时间
    update_time: Optional[str]  # 更新时间


class CnGuideExtra(TypedDict):
    """中文指南扩展表模型 - table_cn_guide_extra"""
    doc_id: str  # 关联主表doc_id
    medical_society: str  # 中华医学会分会
    guide_version: str  # 指南版本（如2024版）
    recommend_class: str  # Ⅰ/Ⅱ/Ⅲ类推荐
    scope: Optional[str]  # 适用范围
    key_points: Optional[str]  # 核心要点摘要


class ClinicalTrial(TypedDict):
    """独立临床试验结构化表模型 - table_clinical_trial"""
    trial_id: str  # 临床试验ID
    source_pmid: Optional[str]  # 关联的PubMed ID
    title: str  # 试验名称
    drug_intervention: str  # 干预药物
    sample_size: int  # 样本量
    endpoint_outcome: str  # 终点结局
    adverse_reaction: Optional[str]  # 不良反应
    publish_year: int  # 发表年份
    disease_tag: Optional[str]  # 疾病标签
    study_type: Optional[str]  # 研究类型：RCT/Meta/观察性研究
    evidence_level: Optional[str]  # 证据等级


# ==================== Chunk文本块模型 ====================
class ChunkMeta(TypedDict):
    """Chunk文本块元数据标准结构"""
    chunk_id: str  # 唯一块ID，如 chunk_doc_cn_0036_5
    doc_id: str  # 所属文档ID
    source_type: Literal["pubmed", "cn_guide", "ctgov"]
    pmid: Optional[str]  # PubMed ID
    cn_guide_code: Optional[str]  # 中文指南编码
    title: str  # 文档标题
    publish_date: str  # 发布日期
    evidence_level: str  # 证据等级
    language: Literal["zh", "en"]
    page: str  # 原始页码
    chunk_index: int  # 块序号
    disease_tag: List[str]  # 疾病标签
    chapter_title: Optional[str]  # 章节标题
    text: str  # 文本内容


# ==================== 问答请求响应模型 ====================
class ChatRequest(TypedDict):
    """问答请求模型"""
    query: str  # 用户问题
    session_id: Optional[str]  # 会话ID（可选）


class RetrievedChunk(TypedDict):
    """检索到的证据块（含完整可追溯元数据）"""
    chunk_id: str
    doc_id: str
    text: str
    score: float  # 相关性分数
    source_type: str
    title: str
    evidence_level: str
    page: str
    section_title: str  # 章节标题
    section_path: str  # 章节路径
    journal: str  # 期刊名
    doi: str  # DOI
    pmid: str  # PMID


class ChatResponse(TypedDict):
    """问答响应模型"""
    answer: str  # LLM生成的答案
    chunks: List[RetrievedChunk]  # 引用的证据块
    has_evidence: bool  # 是否有有效证据
    query: str  # 原始问题
    timestamp: str  # 时间戳


# ==================== 评测结果模型 ====================
class EvaluationResult(TypedDict):
    """单条评测结果"""
    query: str
    answer: str
    ground_truth: str  # 标准答案
    faithfulness: float  # 证据忠实度
    citation_accuracy: float  # 引用准确率
    context_precision: float  # 检索精准率
    answer_relevance: float  # 回答相关性
    retrieved_chunks: List[str]  # 检索到的chunk列表


class EvaluationReport(TypedDict):
    """评测报告"""
    total_count: int  # 测试总数
    avg_faithfulness: float
    avg_citation_accuracy: float
    avg_context_precision: float
    avg_answer_relevance: float
    pass_rate: float  # 达标率
    timestamp: str
    details: List[EvaluationResult]


# ==================== 知识库管理模型 ====================
class DocumentUpload(TypedDict):
    """文档上传信息"""
    file_name: str
    file_path: str
    source_type: Literal["pubmed", "cn_guide", "ctgov"]
    status: Literal["pending", "processing", "completed", "failed"]
    error_message: Optional[str]


class IncrementalTask(TypedDict):
    """增量更新任务"""
    task_id: str
    task_type: Literal["pubmed_monthly", "manual_import"]
    status: Literal["pending", "running", "completed", "failed"]
    start_time: Optional[str]
    end_time: Optional[str]
    processed_count: int
    error_count: int
    log: Optional[str]