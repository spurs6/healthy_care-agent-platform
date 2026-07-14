"""
OpenEvidence 临床证据助手 - 全局配置文件
所有可调整参数统一管理，禁止硬编码在业务代码中
"""
import os
from typing import Dict, Any
from dotenv import load_dotenv


# ==================== 基础路径配置 ====================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CN_GUIDE_DIR = os.path.join(DATA_DIR, "cn_guide")
EN_PUBMED_DIR = os.path.join(DATA_DIR, "en_pubmed")
CHROMA_DB_DIR = os.path.join(DATA_DIR, "chroma_db")
DB_PATH = os.path.join(DATA_DIR, "clinical_kb.db")
TEST_SET_DIR = os.path.join(BASE_DIR, "test_set")

# 先加载项目根目录下的 .env，确保后端启动时能拿到密钥和参数
load_dotenv(os.path.join(BASE_DIR, ".env"))

# 设置离线模式环境变量（必须在导入transformers之前设置）
os.environ["HF_HUB_OFFLINE"] = os.getenv("HF_HUB_OFFLINE", "1")
os.environ["TRANSFORMERS_OFFLINE"] = os.getenv("TRANSFORMERS_OFFLINE", "1")


# ==================== 辅助函数：安全的环境变量解析 ====================
def _env_int(key: str, default: int) -> int:
    """从环境变量安全解析整数，空值回退默认值"""
    val = os.getenv(key, "").strip()
    return int(val) if val else default


def _env_float(key: str, default: float) -> float:
    """从环境变量安全解析浮点数，空值回退默认值"""
    val = os.getenv(key, "").strip()
    return float(val) if val else default


# ==================== 硅基流动LLM配置 ====================
# 支持的模型: deepseek-ai/DeepSeek-V3, Qwen/Qwen2.5-72B-Instruct, 等
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
SILICONFLOW_BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
SILICONFLOW_MODEL = os.getenv("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V3")
LLM_MAX_TOKENS = _env_int("LLM_MAX_TOKENS", 2048)
LLM_TEMPERATURE = _env_float("LLM_TEMPERATURE", 0.1)
LLM_STREAM_TIMEOUT = _env_int("LLM_STREAM_TIMEOUT", 60)
ENABLE_TRANSFORMER_EMBEDDINGS = os.getenv("ENABLE_TRANSFORMER_EMBEDDINGS", "true").lower() == "true"
ENABLE_TRANSFORMER_RERANK = os.getenv("ENABLE_TRANSFORMER_RERANK", "false").lower() == "true"


# ==================== PubMed API配置（实时数据获取）====================
PUBMED_API_KEY = os.getenv("PUBMED_API_KEY", "")
PUBMED_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUBMED_RATE_LIMIT = 3  # 每秒最多请求数
PUBMED_BATCH_SIZE = 100  # 每批获取文献数


# ==================== Chunk切分参数 ====================
CHUNK_WINDOW = _env_int("CHUNK_WINDOW", 600)  # token窗口大小
CHUNK_OVERLAP = _env_int("CHUNK_OVERLAP", 150)  # 重叠token数
MIN_CHUNK_TOKEN = _env_int("MIN_CHUNK_TOKEN", 200)  # 最小chunk token数


# ==================== 检索参数配置 ====================
RECALL_TOP_K = _env_int("RECALL_TOP_K", 10)  # 每个集合召回数量
RERANK_SCORE_THRESHOLD = _env_float("RERANK_SCORE_THRESHOLD", 0.1)  # 重排过滤阈值（降低以支持更多匹配）
FINAL_SEND_LLM_TOP = _env_int("FINAL_SEND_LLM_TOP", 8)  # 送入LLM的证据数量


# ==================== 向量模型配置 ====================
# 使用BGE-large-zh-v1.5，已下载到本地，1024维，中英文效果最优
EMBEDDING_MODEL_EN = "BAAI/bge-large-zh-v1.5"
EMBEDDING_MODEL_ZH = "BAAI/bge-large-zh-v1.5"
RERANK_MODEL = "BAAI/bge-reranker-base"  # Cross-Encoder重排模型

# 本地模型缓存目录
TRANSFORMERS_CACHE = os.path.join(BASE_DIR, "models")
os.environ["TRANSFORMERS_CACHE"] = TRANSFORMERS_CACHE
os.environ["HF_HOME"] = TRANSFORMERS_CACHE
os.environ["HF_HUB_CACHE"] = os.path.join(TRANSFORMERS_CACHE, "hub")
os.environ["HF_HUB_DISABLE_XET"] = "1"


# ==================== ChromaDB配置 ====================
CHROMA_COLLECTIONS = {
    "cn_guide": {
        "name": "coll_cn_guide",
        "weight": 1.5,  # 中文指南最高优先级
        "description": "中华医学会中文临床指南"
    },
    "rct_meta": {
        "name": "coll_rct_meta",
        "weight": 1.0,
        "description": "RCT和Meta分析英文文献"
    },
    "common_study": {
        "name": "coll_common_study",
        "weight": 0.5,  # 普通研究最低优先级
        "description": "普通观察性研究"
    }
}


# ==================== 评测指标底线 ====================
FAITHFULNESS_MIN = _env_float("FAITHFULNESS_MIN", 0.8)
CITATION_ACC_MIN = _env_float("CITATION_ACC_MIN", 0.85)
CONTEXT_PRECISION_MIN = _env_float("CONTEXT_PRECISION_MIN", 0.75)
ANSWER_RELEVANCE_MIN = _env_float("ANSWER_RELEVANCE_MIN", 0.8)


# ==================== Agent配置（自进化）====================
AGENT_MAX_ITERATIONS = _env_int("AGENT_MAX_ITERATIONS", 5)  # Agent最大工具调用轮数
AGENT_SIMILARITY_THRESHOLD = _env_float("AGENT_SIMILARITY_THRESHOLD", 0.7)  # 触发外部检索的相似度阈值
AGENT_EXTERNAL_SEARCH_MAX = _env_int("AGENT_EXTERNAL_SEARCH_MAX", 5)  # 外部检索每次最大返回数
AGENT_ENABLE_SELF_PLAY = os.getenv("AGENT_ENABLE_SELF_PLAY", "false").lower() == "true"  # 是否启用自博弈评估
AGENT_SELF_PLAY_INTERVAL = _env_int("AGENT_SELF_PLAY_INTERVAL", 86400)  # 自博弈评估间隔(秒)


# ==================== 定时任务配置 ====================
MONTHLY_UPDATE_DAY = _env_int("MONTHLY_UPDATE_DAY", 1)  # 每月1日执行
MONTHLY_UPDATE_HOUR = _env_int("MONTHLY_UPDATE_HOUR", 2)  # 凌晨2点执行


# ==================== 领域拦截配置 ====================
ALLOWED_DISEASES = [
    "高血压", "high blood pressure", "hypertension",
    "高血脂", "hyperlipidemia", "dyslipidemia",
    "血脂", "lipid", "cholesterol", "LDL", "HDL", "胆固醇",
    "2型糖尿病", "type 2 diabetes", "T2DM",
    "糖尿病", "diabetes", "HbA1c", "糖化血红蛋白",
    "心脑血管", "cardiovascular", "cerebrovascular",
    "心血管", "cardiac",
    "冠心病", "coronary heart disease", "CHD",
    "心肌梗死", "myocardial infarction", "MI", "AMI", "心梗",
    "脑卒中", "stroke",
    "心力衰竭", "heart failure", "心衰",
    "心房颤动", "atrial fibrillation", "房颤",
    "肾病", "kidney disease", "CKD",
    "代谢综合征", "metabolic syndrome",
    "动脉粥样硬化", "atherosclerosis",
]

# 允许的医学通用词汇（药物名、诊疗操作、检查指标等）
ALLOWED_MEDICAL_TERMS = [
    "药物", "用药", "治疗", "剂量", "副作用", "不良反应",
    "drug", "medication", "treatment", "dose", "side effect",
    "临床", "循证", "指南", "推荐", "证据", "研究",
    "clinical", "evidence", "guideline", "recommendation", "trial",
    # 药物类名
    "他汀", "statin", "ACEI", "ARB", "ARNI", "SGLT2", "GLP-1",
    "二甲双胍", "metformin", "阿司匹林", "aspirin",
    "氯吡格雷", "clopidogrel", "华法林", "warfarin",
    "达比加群", "利伐沙班", "DOAC",
    "β受体阻滞剂", "β阻滞剂", "螺内酯",
    "普利", "沙坦", "列净", "鲁肽",
    # 诊疗操作
    "PCI", "DAPT", "双联抗血小板", "抗凝", "抗血小板",
    "降压", "降糖", "降脂",
    # 检查指标
    "血压", "血糖", "血脂", "肌钙蛋白", "eGFR", "UACR",
]

REJECT_MESSAGE = "【暂无匹配的权威临床循证证据，无法给出诊疗建议】"


# ==================== 循证Prompt模板 ====================
SYSTEM_PROMPT = """你是面向国内临床医生的心脑血管、高血压、高血脂、糖尿病循证证据问答助手，严格遵循以下硬性规则：
1. 仅能使用下方提供的检索证据片段作答，所有临床结论必须标注来源引用[doc_id]，无证据内容绝对禁止编造；
2. 若所有证据片段均无法回答用户问题，直接输出固定文本：【暂无匹配的权威临床循证证据，无法给出诊疗建议】；
3. 区分证据优先级：优先采信《中华医学会临床指南》，其次大样本RCT/Meta分析文献，标注对应证据等级；
4. 双语兼容：中文指南优先展示，英文文献结论翻译为规范医学中文表述；
5. 回答结构固定：①核心诊疗结论 ②分点附带引用标注 ③文末完整引用来源附录；
6. 引用格式统一为[doc_xxxx]，文末附录必须包含：文档来源、标题、证据等级、发布时间。

===== 检索到的临床证据片段开始 =====
{retrieved_chunks}
===== 检索证据结束 =====

用户临床提问：{user_query}"""


# ==================== FastAPI服务配置 ====================
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = _env_int("API_PORT", 8000)
API_DEBUG = os.getenv("API_DEBUG", "false").lower() == "true"
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def get_config_summary() -> Dict[str, Any]:
    """获取配置摘要，用于调试和日志"""
    return {
        "llm_model": SILICONFLOW_MODEL,
        "chunk_window": CHUNK_WINDOW,
        "chunk_overlap": CHUNK_OVERLAP,
        "recall_top_k": RECALL_TOP_K,
        "rerank_threshold": RERANK_SCORE_THRESHOLD,
        "transformer_embeddings": ENABLE_TRANSFORMER_EMBEDDINGS,
        "transformer_rerank": ENABLE_TRANSFORMER_RERANK,
        "faithfulness_min": FAITHFULNESS_MIN,
        "citation_acc_min": CITATION_ACC_MIN,
        "agent_enabled": True,
        "agent_max_iterations": AGENT_MAX_ITERATIONS,
        "agent_similarity_threshold": AGENT_SIMILARITY_THRESHOLD,
        "agent_self_play": AGENT_ENABLE_SELF_PLAY
    }
