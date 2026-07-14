"""
OpenEvidence 临床证据助手 - 离线数据爬取模块
支持爬取Europe PMC开放获取文献库
"""
import os
import time
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime
from tqdm import tqdm
import json

from backend.config import EN_PUBMED_DIR, CN_GUIDE_DIR, ALLOWED_DISEASES
from backend.db_store import article_dao, clinical_trial_dao, ArticleMeta


class EuropePMCCrawler:
    """Europe PMC开放获取文献爬取器"""
    
    def __init__(self, output_dir: str = EN_PUBMED_DIR):
        self.base_url = "https://www.ebi.ac.uk/europepmc/webservices/rest"
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
    
    def search_open_access(self, query: str, max_results: int = 100,
                          open_access: bool = True) -> List[Dict[str, Any]]:
        """
        搜索Europe PMC开放获取文献
        
        Args:
            query: 搜索关键词
            max_results: 最大返回数量
            open_access: 是否只搜索开放获取文献
        
        Returns:
            文献列表
        """
        params = {
            "query": query,
            "format": "json",
            "pageSize": min(max_results, 1000),
            "openAccess": "true" if open_access else "false"
        }
        
        try:
            response = requests.get(
                f"{self.base_url}/search",
                params=params,
                timeout=60
            )
            response.raise_for_status()
            data = response.json()
            
            results = data.get("resultList", {}).get("result", [])
            print(f"[EuropePMC] 搜索'{query}'找到 {len(results)} 篇文献")
            return results
            
        except Exception as e:
            print(f"[EuropePMC] 搜索失败: {e}")
            return []
    
    def fetch_fulltext(self, pmcid: str) -> Optional[str]:
        """
        获取文献全文XML
        
        Args:
            pmcid: PubMed Central ID
        
        Returns:
            全文XML字符串
        """
        try:
            response = requests.get(
                f"{self.base_url}/fullTextXML/{pmcid}",
                timeout=60
            )
            if response.status_code == 200:
                return response.text
            return None
        except Exception as e:
            print(f"[EuropePMC] 获取全文失败 {pmcid}: {e}")
            return None
    
    def download_pdf(self, pmcid: str, output_path: str = None) -> Optional[str]:
        """
        下载开放获取PDF
        
        Args:
            pmcid: PubMed Central ID
            output_path: 保存路径
        
        Returns:
            保存的文件路径
        """
        if output_path is None:
            output_path = os.path.join(self.output_dir, f"{pmcid}.pdf")
        
        # Europe PMC PDF下载链接
        pdf_url = f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf"
        
        try:
            response = requests.get(pdf_url, timeout=120, stream=True)
            if response.status_code == 200:
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"[EuropePMC] 下载PDF成功: {output_path}")
                return output_path
            return None
        except Exception as e:
            print(f"[EuropePMC] 下载PDF失败 {pmcid}: {e}")
            return None
    
    def crawl_by_disease(self, disease: str, max_articles: int = 50) -> List[Dict[str, Any]]:
        """
        按疾病爬取文献
        
        Args:
            disease: 疾病关键词
            max_articles: 最大爬取数量
        
        Returns:
            爬取的文献列表
        """
        # 构建查询 - 临床试验优先
        query = f'({disease}[Title/Abstract]) AND (clinical trial[pt] OR randomized controlled trial[pt] OR meta-analysis[pt])'
        
        results = self.search_open_access(query, max_results=max_articles)
        
        articles = []
        for result in tqdm(results[:max_articles], desc=f"爬取{disease}文献"):
            try:
                pmcid = result.get("pmcid")
                if not pmcid:
                    continue
                
                article = {
                    "pmcid": pmcid,
                    "pmid": result.get("pmid"),
                    "title": result.get("title", ""),
                    "abstract": result.get("abstractText", ""),
                    "authors": [a.get("fullName", "") for a in result.get("authorList", {}).get("author", [])],
                    "journal": result.get("journalTitle", ""),
                    "publish_year": int(result.get("pubYear", 0)) if result.get("pubYear") else None,
                    "doi": result.get("doi"),
                    "isOpenAccess": result.get("isOpenAccess", "N") == "Y",
                    "source_type": "pubmed",
                    "language": "en"
                }
                
                # 尝试下载PDF
                if article["isOpenAccess"]:
                    pdf_path = self.download_pdf(pmcid)
                    if pdf_path:
                        article["pdf_path"] = pdf_path
                
                articles.append(article)
                time.sleep(0.5)  # 遵守速率限制
                
            except Exception as e:
                print(f"[EuropePMC] 处理文献失败: {e}")
                continue
        
        return articles
    
    def batch_crawl_diseases(self, diseases: List[str] = None, 
                            articles_per_disease: int = 30) -> Dict[str, int]:
        """
        批量爬取多种疾病的文献
        
        Args:
            diseases: 疾病列表
            articles_per_disease: 每种疾病爬取数量
        
        Returns:
            每种疾病的爬取数量统计
        """
        if diseases is None:
            diseases = ["hypertension", "diabetes mellitus type 2", 
                       "hyperlipidemia", "cardiovascular disease", "stroke"]
        
        stats = {}
        for disease in diseases:
            print(f"\n[EuropePMC] 开始爬取疾病: {disease}")
            articles = self.crawl_by_disease(disease, max_articles=articles_per_disease)
            
            # 保存到数据库
            saved = self.save_to_database(articles)
            stats[disease] = saved
        
        return stats
    
    def save_to_database(self, articles: List[Dict[str, Any]]) -> int:
        """保存到数据库"""
        saved_count = 0
        for article in articles:
            try:
                doc_id = f"doc_en_{article.get('pmid') or article.get('pmcid')}"

                # 提取疾病标签
                disease_tags = self._extract_disease_tags(article.get("title", "") + " " + article.get("abstract", ""))

                meta: ArticleMeta = {
                    "doc_id": doc_id,
                    "source_type": "pubmed",
                    "title": article["title"],
                    "publish_year": article.get("publish_year"),
                    "evidence_level": self._infer_evidence_level(article),
                    "language": "en",
                    "disease_tags": disease_tags,
                    "file_path": article.get("pdf_path", ""),
                    "pmid": article.get("pmid"),
                    "doi": article.get("doi"),
                    "abstract": article.get("abstract"),
                    "keywords": [],
                    "authors": article.get("authors", []),
                    "journal": article.get("journal"),
                    "create_time": datetime.now().isoformat(),
                    "update_time": datetime.now().isoformat()
                }

                if article_dao.insert(meta):
                    saved_count += 1

            except Exception as e:
                print(f"[EuropePMC] 保存文献失败: {e}")
                continue

        return saved_count
    
    def _infer_evidence_level(self, article: Dict) -> str:
        """推断证据等级"""
        abstract = article.get("abstract", "").lower()
        if "randomized" in abstract or "rct" in abstract:
            return "1A"
        elif "meta-analysis" in abstract:
            return "1A"
        elif "cohort" in abstract:
            return "2B"
        else:
            return "3B"

    def _extract_disease_tags(self, text: str) -> list:
        """从文本中提取疾病标签"""
        tags = []
        text_lower = text.lower()
        for disease in ALLOWED_DISEASES:
            if disease.lower() in text_lower:
                tags.append(disease)
        return list(set(tags))[:5]  # 最多5个，去重


class CnGuideImporter:
    """中文指南导入器 - 处理本地PDF文件"""
    
    def __init__(self, input_dir: str = CN_GUIDE_DIR):
        self.input_dir = input_dir
        os.makedirs(input_dir, exist_ok=True)
    
    def scan_local_pdfs(self) -> List[str]:
        """扫描本地PDF文件"""
        pdf_files = []
        for root, dirs, files in os.walk(self.input_dir):
            for file in files:
                if file.lower().endswith('.pdf'):
                    pdf_files.append(os.path.join(root, file))
        return pdf_files
    
    def import_from_metadata_file(self, metadata_file: str) -> int:
        """
        从元数据JSON文件批量导入
        
        Args:
            metadata_file: 元数据文件路径，格式:
                [{
                    "file_path": "/path/to/guide.pdf",
                    "title": "指南标题",
                    "medical_society": "中华医学会心血管病学分会",
                    "guide_version": "2024版",
                    "recommend_class": "Ⅰ",
                    "disease_tags": ["高血压", "冠心病"]
                }, ...]
        
        Returns:
            导入数量
        """
        with open(metadata_file, 'r', encoding='utf-8') as f:
            guides = json.load(f)
        
        imported = 0
        for i, guide in enumerate(guides):
            try:
                doc_id = f"doc_cn_{i:04d}"
                
                meta: ArticleMeta = {
                    "doc_id": doc_id,
                    "source_type": "cn_guide",
                    "title": guide.get("title", f"中文指南_{i}"),
                    "publish_year": guide.get("publish_year", datetime.now().year),
                    "evidence_level": guide.get("evidence_level", "1A"),
                    "language": "zh",
                    "disease_tags": guide.get("disease_tags", []),
                    "file_path": guide.get("file_path", ""),
                    "pmid": None,
                    "doi": None,
                    "abstract": guide.get("abstract"),
                    "keywords": [],
                    "authors": [],
                    "journal": None,
                    "create_time": datetime.now().isoformat(),
                    "update_time": datetime.now().isoformat()
                }
                
                if article_dao.insert(meta):
                    imported += 1
                    
            except Exception as e:
                print(f"[CnGuide] 导入失败: {e}")
                continue
        
        print(f"[CnGuide] 成功导入 {imported} 篇中文指南")
        return imported


class ClinicalTrialsImporter:
    """ClinicalTrials.gov数据导入器"""
    
    def __init__(self):
        self.base_url = "https://clinicaltrials.gov/api/v2/studies"
    
    def search_trials(self, condition: str, max_results: int = 100) -> List[Dict]:
        """搜索临床试验"""
        params = {
            "query.cond": condition,
            "pageSize": max_results,
            "format": "json"
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=60)
            response.raise_for_status()
            data = response.json()
            
            studies = data.get("studies", [])
            print(f"[ClinicalTrials] 搜索'{condition}'找到 {len(studies)} 个试验")
            return studies
            
        except Exception as e:
            print(f"[ClinicalTrials] 搜索失败: {e}")
            return []
    
    def parse_trial(self, study: Dict) -> Dict:
        """解析临床试验数据"""
        protocol = study.get("protocolSection", {})

        # 安全提取发布年份，避免空字符串
        date_str = protocol.get("statusModule", {}).get("startDateStruct", {}).get("date", "")
        publish_year = int(date_str[:4]) if date_str and len(date_str) >= 4 else None

        return {
            "trial_id": protocol.get("identificationModule", {}).get("nctId", ""),
            "title": protocol.get("identificationModule", {}).get("officialTitle", ""),
            "drug_intervention": ", ".join([
                i.get("name", "")
                for i in protocol.get("armsInterventionsModule", {}).get("interventions", [])
            ]),
            "sample_size": protocol.get("designModule", {}).get("enrollmentInfo", {}).get("count", 0),
            "endpoint_outcome": ", ".join([
                o.get("description", "")
                for o in protocol.get("outcomesModule", {}).get("primaryOutcomes", [])
            ]),
            "publish_year": publish_year,
            "disease_tag": protocol.get("conditionsModule", {}).get("conditions", [""])[0],
            "study_type": protocol.get("designModule", {}).get("studyType", ""),
            "source_pmid": None,
            "adverse_reaction": None,
            "evidence_level": "1B"  # 临床试验默认为1B
        }

    def save_to_database(self, trials: List[Dict]) -> int:
        """
        保存临床试验数据到数据库

        Args:
            trials: 临床试验列表（已调用parse_trial）

        Returns:
            成功保存数量
        """
        saved_count = 0
        for trial in trials:
            try:
                if clinical_trial_dao.insert(trial):
                    saved_count += 1
            except Exception as e:
                print(f"[ClinicalTrials] 保存试验失败: {e}")
                continue

        print(f"[ClinicalTrials] 成功保存 {saved_count} 个临床试验到数据库")
        return saved_count


# 全局实例
europepmc_crawler = EuropePMCCrawler()
cn_guide_importer = CnGuideImporter()
clinical_trials_importer = ClinicalTrialsImporter()