"""
OpenEvidence 临床证据助手 - 数据库操作模块
SQLite数据库初始化和DAO层封装
"""
import sqlite3
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

from backend.config import DB_PATH
from backend.db_store.models import ArticleMeta, CnGuideExtra, ClinicalTrial


class DatabaseManager:
    """数据库管理器 - 单例模式"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.init_database()
    
    def init_database(self):
        """初始化数据库，创建所有表"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 表1：通用文献元数据表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS table_article_meta (
                    doc_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    publish_year INTEGER,
                    evidence_level TEXT,
                    language TEXT NOT NULL,
                    disease_tags TEXT,
                    file_path TEXT,
                    pmid TEXT,
                    doi TEXT,
                    abstract TEXT,
                    keywords TEXT,
                    authors TEXT,
                    journal TEXT,
                    create_time TEXT,
                    update_time TEXT
                )
            """)
            
            # 表2：中文指南扩展表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS table_cn_guide_extra (
                    doc_id TEXT PRIMARY KEY,
                    medical_society TEXT,
                    guide_version TEXT,
                    recommend_class TEXT,
                    scope TEXT,
                    key_points TEXT,
                    FOREIGN KEY (doc_id) REFERENCES table_article_meta(doc_id)
                )
            """)
            
            # 表3：独立临床试验结构化表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS table_clinical_trial (
                    trial_id TEXT PRIMARY KEY,
                    source_pmid TEXT,
                    title TEXT,
                    drug_intervention TEXT,
                    sample_size INTEGER,
                    endpoint_outcome TEXT,
                    adverse_reaction TEXT,
                    publish_year INTEGER,
                    disease_tag TEXT,
                    study_type TEXT,
                    evidence_level TEXT
                )
            """)
            
            # 表4：增量任务记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS table_incremental_task (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    start_time TEXT,
                    end_time TEXT,
                    processed_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    log TEXT
                )
            """)

            # 表5：Agent经验记忆表（自进化Phase 2）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS table_agent_experience (
                    exp_id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    query_type TEXT,
                    disease_tags TEXT,
                    strategy TEXT,
                    outcome TEXT,
                    tool_calls TEXT,
                    answer TEXT,
                    timestamp TEXT,
                    auto_eval_score REAL
                )
            """)

            # 表6：知识缺口记录表（自进化Phase 2）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS table_knowledge_gap (
                    gap_id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    gap_type TEXT,
                    max_similarity REAL,
                    domain TEXT,
                    external_source TEXT,
                    external_results_count INTEGER DEFAULT 0,
                    fetched_articles TEXT,
                    resolved INTEGER DEFAULT 0,
                    timestamp TEXT
                )
            """)

            # 表7：策略优化记录表（自进化Phase 2）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS table_strategy_optimization (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_type TEXT NOT NULL,
                    best_bm25_weight REAL,
                    best_vector_weight REAL,
                    best_rerank_threshold REAL,
                    best_final_top_n INTEGER,
                    sample_count INTEGER DEFAULT 0,
                    avg_score REAL,
                    updated_at TEXT
                )
            """)

            # 表8：推理原则库（自进化Phase 3 - 推理自进化）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS table_reasoning_principle (
                    principle_id TEXT PRIMARY KEY,
                    query_type TEXT NOT NULL,
                    disease_tags TEXT,
                    principle TEXT NOT NULL,
                    source_experiences TEXT,
                    confidence REAL DEFAULT 0.5,
                    usage_count INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT,
                    status TEXT DEFAULT 'active'
                )
            """)

            # 表9：安全审计日志（自进化安全防护）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS table_evolution_audit (
                    audit_id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    target_table TEXT,
                    target_id TEXT,
                    change_summary TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    risk_level TEXT DEFAULT 'low',
                    requires_review INTEGER DEFAULT 0,
                    reviewed INTEGER DEFAULT 0,
                    reviewer TEXT,
                    review_note TEXT,
                    timestamp TEXT
                )
            """)

            # 表10：评测历史记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS table_eval_history (
                    eval_id TEXT PRIMARY KEY,
                    test_set_filename TEXT NOT NULL,
                    total_count INTEGER,
                    avg_faithfulness REAL,
                    avg_citation_accuracy REAL,
                    avg_context_precision REAL,
                    avg_answer_relevance REAL,
                    pass_rate REAL,
                    details TEXT,
                    timestamp TEXT
                )
            """)

            # 创建索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_article_source ON table_article_meta(source_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_article_year ON table_article_meta(publish_year)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_article_pmid ON table_article_meta(pmid)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trial_disease ON table_clinical_trial(disease_tag)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_exp_query_type ON table_agent_experience(query_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_gap_domain ON table_knowledge_gap(domain)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_principle_type ON table_reasoning_principle(query_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_target ON table_evolution_audit(target_table, target_id)
            """)
            
            conn.commit()
            print(f"[Database] 数据库初始化完成: {DB_PATH}")
    
    @contextmanager
    def get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


# ==================== DAO层封装 ====================
class ArticleDAO:
    """文献元数据DAO"""
    
    def __init__(self, db: DatabaseManager = None):
        self.db = db or DatabaseManager()
    
    def insert(self, article: ArticleMeta) -> bool:
        """插入文献元数据"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO table_article_meta 
                    (doc_id, source_type, title, publish_year, evidence_level, language,
                     disease_tags, file_path, pmid, doi, abstract, keywords, authors, 
                     journal, create_time, update_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    article["doc_id"],
                    article["source_type"],
                    article["title"],
                    article.get("publish_year"),
                    article.get("evidence_level", ""),
                    article["language"],
                    json.dumps(article.get("disease_tags", []), ensure_ascii=False),
                    article.get("file_path", ""),
                    article.get("pmid"),
                    article.get("doi"),
                    article.get("abstract"),
                    json.dumps(article.get("keywords", []), ensure_ascii=False),
                    json.dumps(article.get("authors", []), ensure_ascii=False),
                    article.get("journal"),
                    article.get("create_time", datetime.now().isoformat()),
                    article.get("update_time", datetime.now().isoformat())
                ))
                conn.commit()
                return True
            except Exception as e:
                print(f"[ArticleDAO] 插入失败: {e}")
                return False
    
    def get_by_doc_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """根据doc_id获取文献"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM table_article_meta WHERE doc_id = ?", (doc_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None
    
    def search(self, source_type: str = None, disease: str = None,
               year_from: int = None, year_to: int = None,
               evidence_level: str = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """多条件搜索文献"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            sql = "SELECT * FROM table_article_meta WHERE 1=1"
            params = []

            if source_type:
                sql += " AND source_type = ?"
                params.append(source_type)

            if disease:
                sql += " AND disease_tags LIKE ?"
                params.append(f'%{disease}%')

            if year_from:
                sql += " AND publish_year >= ?"
                params.append(year_from)

            if year_to:
                sql += " AND publish_year <= ?"
                params.append(year_to)

            if evidence_level:
                sql += " AND evidence_level = ?"
                params.append(evidence_level)

            sql += f" ORDER BY publish_year DESC LIMIT {limit} OFFSET {offset}"

            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]
    
    def get_all_doc_ids(self, source_type: str = None) -> List[str]:
        """获取所有文档ID"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if source_type:
                cursor.execute(
                    "SELECT doc_id FROM table_article_meta WHERE source_type = ?",
                    (source_type,)
                )
            else:
                cursor.execute("SELECT doc_id FROM table_article_meta")
            return [row["doc_id"] for row in cursor.fetchall()]
    
    def count(self, source_type: str = None) -> int:
        """统计文献数量"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if source_type:
                cursor.execute(
                    "SELECT COUNT(*) FROM table_article_meta WHERE source_type = ?",
                    (source_type,)
                )
            else:
                cursor.execute("SELECT COUNT(*) FROM table_article_meta")
            return cursor.fetchone()[0]

    def count_with_filters(self, source_type: str = None, disease: str = None,
                           year_from: int = None, year_to: int = None,
                           evidence_level: str = None) -> int:
        """多条件统计文献数量（用于分页）"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            sql = "SELECT COUNT(*) FROM table_article_meta WHERE 1=1"
            params = []
            if source_type:
                sql += " AND source_type = ?"
                params.append(source_type)
            if disease:
                sql += " AND disease_tags LIKE ?"
                params.append(f'%{disease}%')
            if year_from:
                sql += " AND publish_year >= ?"
                params.append(year_from)
            if year_to:
                sql += " AND publish_year <= ?"
                params.append(year_to)
            if evidence_level:
                sql += " AND evidence_level = ?"
                params.append(evidence_level)
            cursor.execute(sql, params)
            return cursor.fetchone()[0]
    
    def delete(self, doc_id: str) -> bool:
        """删除文献"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM table_article_meta WHERE doc_id = ?", (doc_id,))
                conn.commit()
                return True
            except Exception as e:
                print(f"[ArticleDAO] 删除失败: {e}")
                return False
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        return {
            "doc_id": row["doc_id"],
            "source_type": row["source_type"],
            "title": row["title"],
            "publish_year": row["publish_year"],
            "evidence_level": row["evidence_level"],
            "language": row["language"],
            "disease_tags": json.loads(row["disease_tags"]) if row["disease_tags"] else [],
            "file_path": row["file_path"],
            "pmid": row["pmid"],
            "doi": row["doi"],
            "abstract": row["abstract"],
            "keywords": json.loads(row["keywords"]) if row["keywords"] else [],
            "authors": json.loads(row["authors"]) if row["authors"] else [],
            "journal": row["journal"],
            "create_time": row["create_time"],
            "update_time": row["update_time"]
        }


class CnGuideDAO:
    """中文指南扩展DAO"""
    
    def __init__(self, db: DatabaseManager = None):
        self.db = db or DatabaseManager()
    
    def insert(self, guide: CnGuideExtra) -> bool:
        """插入中文指南扩展信息"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO table_cn_guide_extra 
                    (doc_id, medical_society, guide_version, recommend_class, scope, key_points)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    guide["doc_id"],
                    guide.get("medical_society"),
                    guide.get("guide_version"),
                    guide.get("recommend_class"),
                    guide.get("scope"),
                    guide.get("key_points")
                ))
                conn.commit()
                return True
            except Exception as e:
                print(f"[CnGuideDAO] 插入失败: {e}")
                return False
    
    def get_by_doc_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """根据doc_id获取中文指南扩展信息"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM table_cn_guide_extra WHERE doc_id = ?", (doc_id,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None


class ClinicalTrialDAO:
    """临床试验DAO"""
    
    def __init__(self, db: DatabaseManager = None):
        self.db = db or DatabaseManager()
    
    def insert(self, trial: ClinicalTrial) -> bool:
        """插入临床试验数据"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO table_clinical_trial 
                    (trial_id, source_pmid, title, drug_intervention, sample_size,
                     endpoint_outcome, adverse_reaction, publish_year, disease_tag,
                     study_type, evidence_level)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trial["trial_id"],
                    trial.get("source_pmid"),
                    trial["title"],
                    trial["drug_intervention"],
                    trial.get("sample_size", 0),
                    trial["endpoint_outcome"],
                    trial.get("adverse_reaction"),
                    trial.get("publish_year"),
                    trial.get("disease_tag"),
                    trial.get("study_type"),
                    trial.get("evidence_level")
                ))
                conn.commit()
                return True
            except Exception as e:
                print(f"[ClinicalTrialDAO] 插入失败: {e}")
                return False
    
    def search(self, drug: str = None, disease: str = None, 
               min_sample: int = None, limit: int = 100) -> List[Dict[str, Any]]:
        """搜索临床试验"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            sql = "SELECT * FROM table_clinical_trial WHERE 1=1"
            params = []
            
            if drug:
                sql += " AND drug_intervention LIKE ?"
                params.append(f'%{drug}%')
            
            if disease:
                sql += " AND disease_tag LIKE ?"
                params.append(f'%{disease}%')
            
            if min_sample:
                sql += " AND sample_size >= ?"
                params.append(min_sample)
            
            sql += f" ORDER BY sample_size DESC LIMIT {limit}"
            
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]


class TaskDAO:
    """增量任务DAO"""
    
    def __init__(self, db: DatabaseManager = None):
        self.db = db or DatabaseManager()
    
    def create_task(self, task_id: str, task_type: str) -> bool:
        """创建增量任务"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO table_incremental_task 
                    (task_id, task_type, status, start_time)
                    VALUES (?, ?, 'running', ?)
                """, (task_id, task_type, datetime.now().isoformat()))
                conn.commit()
                return True
            except Exception as e:
                print(f"[TaskDAO] 创建任务失败: {e}")
                return False
    
    def update_task(self, task_id: str, status: str, processed: int = 0, 
                    error: int = 0, log: str = None) -> bool:
        """更新任务状态"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE table_incremental_task 
                    SET status = ?, processed_count = processed_count + ?,
                        error_count = error_count + ?, log = ?,
                        end_time = ?
                    WHERE task_id = ?
                """, (status, processed, error, log, datetime.now().isoformat(), task_id))
                conn.commit()
                return True
            except Exception as e:
                print(f"[TaskDAO] 更新任务失败: {e}")
                return False
    
    def get_latest_task(self, task_type: str = None) -> Optional[Dict[str, Any]]:
        """获取最新的任务"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if task_type:
                cursor.execute("""
                    SELECT * FROM table_incremental_task
                    WHERE task_type = ?
                    ORDER BY start_time DESC LIMIT 1
                """, (task_type,))
            else:
                cursor.execute("""
                    SELECT * FROM table_incremental_task
                    ORDER BY start_time DESC LIMIT 1
                """)
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_by_task_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """按task_id获取任务"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM table_incremental_task WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


# 全局数据库实例
db_manager = DatabaseManager()
article_dao = ArticleDAO(db_manager)
cn_guide_dao = CnGuideDAO(db_manager)
clinical_trial_dao = ClinicalTrialDAO(db_manager)
task_dao = TaskDAO(db_manager)