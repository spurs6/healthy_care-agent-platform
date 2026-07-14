"""
OpenEvidence 临床证据助手 - 数据库初始化脚本
仅初始化数据库结构，不创建任何伪造数据
所有数据必须来自真实权威数据源：
- PubMed API: https://pubmed.ncbi.nlm.nih.gov/
- Europe PMC: https://europepmc.org/
- 中华医学会指南: 手动上传PDF
- ClinicalTrials.gov: https://clinicaltrials.gov/
"""
import os
import sys
import sqlite3

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 直接定义路径，不依赖backend包
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CN_GUIDE_DIR = os.path.join(DATA_DIR, "cn_guide")
EN_PUBMED_DIR = os.path.join(DATA_DIR, "en_pubmed")
CHROMA_DB_DIR = os.path.join(DATA_DIR, "chroma_db")
DB_PATH = os.path.join(DATA_DIR, "clinical_kb.db")
TEST_SET_DIR = os.path.join(BASE_DIR, "test_set")


def init_directories():
    """创建必要目录"""
    directories = [
        CN_GUIDE_DIR,
        EN_PUBMED_DIR,
        CHROMA_DB_DIR,
        TEST_SET_DIR,
        "models"
    ]

    for dir_path in directories:
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
            print(f"[OK] 创建目录: {dir_path}")
        else:
            print(f"  目录已存在: {dir_path}")


def init_database():
    """初始化数据库结构（不插入任何伪造数据）"""
    print("\n初始化SQLite数据库...")

    conn = sqlite3.connect(DB_PATH)
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

    # 创建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_article_source ON table_article_meta(source_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_article_year ON table_article_meta(publish_year)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_article_pmid ON table_article_meta(pmid)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trial_disease ON table_clinical_trial(disease_tag)")

    conn.commit()

    # 检查表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"[OK] 数据库表已创建: {[t[0] for t in tables]}")

    conn.close()
    print(f"[OK] 数据库初始化完成: {DB_PATH}")


def print_data_sources():
    """打印真实数据源信息"""
    print("\n" + "=" * 60)
    print("真实数据源获取指南")
    print("=" * 60)

    print("\n[方式一] PubMed API实时获取")
    print("- 数据源: https://pubmed.ncbi.nlm.nih.gov/")
    print("- 使用方法:")
    print("  1. 获取API密钥: https://www.ncbi.nlm.nih.gov/account/")
    print("  2. 配置.env文件中的PUBMED_API_KEY")
    print("  3. 调用API获取最新文献")

    print("\n[方式二] Europe PMC离线下载")
    print("- 数据源: https://europepmc.org/")
    print("- 使用方法:")
    print("  1. 访问 https://europepmc.org/advancedsearch")
    print("  2. 搜索条件: hypertension OR diabetes OR hyperlipidemia")
    print("  3. 下载开放获取PDF文件")
    print("  4. 将PDF放入 data/en_pubmed/ 目录")

    print("\n[方式三] 中文临床指南")
    print("- 数据源: 中华医学会各分会官网")
    print("- 推荐指南:")
    print("  - 中国高血压防治指南: 中华医学会心血管病学分会")
    print("  - 中国糖尿病防治指南: 中华医学会糖尿病学分会")
    print("  - 中国血脂管理指南: 中华医学会心血管病学分会")
    print("- 使用方法:")
    print("  1. 从官网下载PDF")
    print("  2. 将PDF放入 data/cn_guide/ 目录")

    print("\n[方式四] ClinicalTrials.gov")
    print("- 数据源: https://clinicaltrials.gov/")
    print("- 使用方法:")
    print("  1. 搜索相关临床试验")
    print("  2. 导出CSV格式数据")
    print("  3. 通过知识库管理页面上传")


def print_next_steps():
    """打印后续步骤"""
    print("\n" + "=" * 60)
    print("初始化完成！后续操作步骤")
    print("=" * 60)

    print("\n1. 配置API密钥（如需实时数据获取）")
    print("   编辑 .env 文件，填写:")
    print("   - SILICONFLOW_API_KEY: 硅基流动API密钥（已配置）")
    print("   - PUBMED_API_KEY: PubMed API密钥（可选）")

    print("\n2. 安装Python依赖")
    print("   pip install -r requirements.txt")

    print("\n3. 启动后端服务")
    print("   cd backend && python main.py")
    print("   访问: http://localhost:8000")

    print("\n4. 启动前端服务（另一个终端）")
    print("   cd frontend")
    print("   npm install")
    print("   npm run dev")
    print("   访问: http://localhost:5173")

    print("\n5. 导入真实数据")
    print("   - 中文指南PDF放入 data/cn_guide/")
    print("   - 英文文献PDF放入 data/en_pubmed/")
    print("   - 通过前端处理按钮构建向量索引")


def main():
    """主初始化流程"""
    print("=" * 60)
    print("OpenEvidence 临床证据助手 - 数据库初始化")
    print("注意：不创建任何伪造数据，所有数据需从权威来源获取")
    print("=" * 60)

    # 1. 创建目录
    init_directories()

    # 2. 初始化数据库结构
    init_database()

    # 3. 打印数据源信息
    print_data_sources()

    # 4. 打印后续步骤
    print_next_steps()


if __name__ == "__main__":
    main()
