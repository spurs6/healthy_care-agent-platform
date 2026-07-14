"""
OpenEvidence 临床证据助手 - 数据获取模块
"""
from backend.data_collect.pubmed_api import PubMedFetcher, pubmed_fetcher
from backend.data_collect.offline_crawler import (
    EuropePMCCrawler, CnGuideImporter, ClinicalTrialsImporter,
    europepmc_crawler, cn_guide_importer, clinical_trials_importer
)

# scheduler模块可选导入（需要apscheduler）
try:
    from backend.data_collect.scheduler import DataUpdateScheduler, scheduler
    __all__ = [
        # PubMed API
        "PubMedFetcher", "pubmed_fetcher",
        # 离线爬取
        "EuropePMCCrawler", "europepmc_crawler",
        "CnGuideImporter", "cn_guide_importer",
        "ClinicalTrialsImporter", "clinical_trials_importer",
        # 调度器
        "DataUpdateScheduler", "scheduler"
    ]
except ImportError:
    __all__ = [
        # PubMed API
        "PubMedFetcher", "pubmed_fetcher",
        # 离线爬取
        "EuropePMCCrawler", "europepmc_crawler",
        "CnGuideImporter", "cn_guide_importer",
        "ClinicalTrialsImporter", "clinical_trials_importer"
    ]