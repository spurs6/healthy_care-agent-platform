"""
OpenEvidence 临床证据助手 - PubMed API数据获取模块
支持实时API调用获取最新文献数据
"""
import time
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from tqdm import tqdm

from backend.config import (
    PUBMED_API_KEY, PUBMED_BASE_URL, PUBMED_RATE_LIMIT, PUBMED_BATCH_SIZE,
    EN_PUBMED_DIR, ALLOWED_DISEASES
)
from backend.db_store import article_dao, ArticleMeta


class PubMedFetcher:
    """PubMed API数据获取器"""
    
    def __init__(self):
        self.base_url = PUBMED_BASE_URL
        self.api_key = PUBMED_API_KEY
        self.rate_limit_delay = 1.0 / PUBMED_RATE_LIMIT if PUBMED_RATE_LIMIT > 0 else 0.34
        self.headers = {"User-Agent": "OpenEvidence/1.0"}
        if self.api_key:
            self.headers["api_key"] = self.api_key
    
    def search_articles(self, query: str, max_results: int = 100, 
                       date_from: str = None, date_to: str = None) -> List[str]:
        """
        搜索PubMed文献，返回PMID列表
        
        Args:
            query: 搜索关键词
            max_results: 最大返回数量
            date_from: 起始日期 (YYYY/MM/DD)
            date_to: 结束日期 (YYYY/MM/DD)
        
        Returns:
            PMID列表
        """
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
            "sort": "relevance"
        }
        
        # 添加日期过滤
        if date_from and date_to:
            params["datetype"] = "pdat"
            params["mindate"] = date_from
            params["maxdate"] = date_to
        
        try:
            response = requests.get(
                f"{self.base_url}/esearch.fcgi",
                params=params,
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            id_list = data.get("esearchresult", {}).get("idlist", [])
            print(f"[PubMed] 搜索'{query}'找到 {len(id_list)} 篇文献")
            return id_list
            
        except Exception as e:
            print(f"[PubMed] 搜索失败: {e}")
            return []
    
    def fetch_article_details(self, pmids: List[str]) -> List[Dict[str, Any]]:
        """
        批量获取文献详细信息
        
        Args:
            pmids: PMID列表
        
        Returns:
            文献详情列表
        """
        if not pmids:
            return []
        
        articles = []
        # 分批获取
        for i in tqdm(range(0, len(pmids), PUBMED_BATCH_SIZE), desc="获取文献详情"):
            batch = pmids[i:i + PUBMED_BATCH_SIZE]
            
            params = {
                "db": "pubmed",
                "id": ",".join(batch),
                "retmode": "xml"
            }
            
            try:
                response = requests.get(
                    f"{self.base_url}/efetch.fcgi",
                    params=params,
                    headers=self.headers,
                    timeout=60
                )
                response.raise_for_status()
                
                # 解析XML
                root = ET.fromstring(response.content)
                for article_elem in root.findall(".//PubmedArticle"):
                    article = self._parse_article_xml(article_elem)
                    if article:
                        articles.append(article)
                
                # 遵守速率限制
                time.sleep(self.rate_limit_delay)
                
            except Exception as e:
                print(f"[PubMed] 获取批次详情失败: {e}")
                continue
        
        return articles
    
    def _parse_article_xml(self, article_elem) -> Optional[Dict[str, Any]]:
        """解析单篇文献XML"""
        try:
            medline = article_elem.find("MedlineCitation")
            pmid = medline.find("PMID").text if medline.find("PMID") is not None else None
            
            article = medline.find("Article")
            if article is None:
                return None
            
            # 标题
            title_elem = article.find("ArticleTitle")
            title = title_elem.text if title_elem is not None and title_elem.text else ""
            
            # 摘要
            abstract_texts = article.findall(".//Abstract/AbstractText")
            abstract = " ".join([t.text for t in abstract_texts if t.text])
            
            # 作者
            authors = []
            author_list = article.find("AuthorList")
            if author_list is not None:
                for author in author_list.findall("Author"):
                    lastname = author.find("LastName")
                    forename = author.find("ForeName")
                    if lastname is not None:
                        name = lastname.text
                        if forename is not None:
                            name += f" {forename.text}"
                        authors.append(name)
            
            # 期刊
            journal_elem = article.find("Journal/Title")
            journal = journal_elem.text if journal_elem is not None else ""
            
            # 发表年份
            year = None
            pub_date = article.find("Journal/JournalIssue/PubDate/Year")
            if pub_date is not None:
                year = int(pub_date.text)
            else:
                medline_date = article.find("Journal/JournalIssue/PubDate/MedlineDate")
                if medline_date is not None and medline_date.text:
                    year = int(medline_date.text[:4])
            
            # 关键词
            keywords = []
            keyword_list = medline.find("KeywordList")
            if keyword_list is not None:
                for kw in keyword_list.findall("Keyword"):
                    if kw.text:
                        keywords.append(kw.text)
            
            # MeSH主题词作为疾病标签
            mesh_terms = []
            mesh_heading_list = medline.find("MeshHeadingList")
            if mesh_heading_list is not None:
                for mesh in mesh_heading_list.findall("MeshHeading"):
                    descriptor = mesh.find("DescriptorName")
                    if descriptor is not None and descriptor.text:
                        mesh_terms.append(descriptor.text)
            
            # DOI
            doi = None
            for eloc in article.findall(".//ELocationID"):
                if eloc.get("EIdType") == "doi":
                    doi = eloc.text
                    break
            
            return {
                "pmid": pmid,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "journal": journal,
                "publish_year": year,
                "keywords": keywords,
                "mesh_terms": mesh_terms,
                "doi": doi,
                "source_type": "pubmed",
                "language": "en"
            }
            
        except Exception as e:
            print(f"[PubMed] 解析文章XML失败: {e}")
            return None
    
    def fetch_monthly_incremental(self, disease_keywords: List[str] = None, 
                                  days: int = 30) -> List[Dict[str, Any]]:
        """
        获取月度增量文献
        
        Args:
            disease_keywords: 疾病关键词列表，默认使用配置中的ALLOWED_DISEASES
            days: 获取最近N天的文献
        
        Returns:
            文献列表
        """
        if disease_keywords is None:
            # 使用允许的疾病关键词
            disease_keywords = list(set([
                kw for kw in ALLOWED_DISEASES 
                if not any(c in kw for c in ['/', ' ']) or kw in ['hypertension', 'diabetes', 'stroke']
            ]))
        
        # 构建搜索查询
        query = " OR ".join([f'"{kw}"[MeSH Terms]' for kw in disease_keywords[:10]])
        query = f"({query}) AND (clinical trial[pt] OR meta-analysis[pt] OR randomized controlled trial[pt])"
        
        # 日期范围
        date_to = datetime.now().strftime("%Y/%m/%d")
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
        
        print(f"[PubMed] 开始获取 {date_from} 到 {date_to} 的增量文献...")
        
        # 搜索
        pmids = self.search_articles(query, max_results=200, 
                                     date_from=date_from, date_to=date_to)
        
        if not pmids:
            return []
        
        # 获取详情
        articles = self.fetch_article_details(pmids)
        
        print(f"[PubMed] 成功获取 {len(articles)} 篇增量文献")
        return articles
    
    def save_to_database(self, articles: List[Dict[str, Any]]) -> int:
        """
        保存文献到数据库
        
        Args:
            articles: 文献列表
        
        Returns:
            成功保存数量
        """
        saved_count = 0
        for article in articles:
            try:
                # 生成doc_id
                doc_id = f"doc_en_{article['pmid']}"
                
                # 提取疾病标签
                disease_tags = self._extract_disease_tags(article.get("mesh_terms", []))
                
                # 构建元数据
                meta: ArticleMeta = {
                    "doc_id": doc_id,
                    "source_type": "pubmed",
                    "title": article["title"],
                    "publish_year": article.get("publish_year"),
                    "evidence_level": self._infer_evidence_level(article),
                    "language": "en",
                    "disease_tags": disease_tags,
                    "file_path": "",  # 待后续下载PDF填充
                    "pmid": article["pmid"],
                    "doi": article.get("doi"),
                    "abstract": article.get("abstract"),
                    "keywords": article.get("keywords", []),
                    "authors": article.get("authors", []),
                    "journal": article.get("journal"),
                    "create_time": datetime.now().isoformat(),
                    "update_time": datetime.now().isoformat()
                }
                
                if article_dao.insert(meta):
                    saved_count += 1
                    
            except Exception as e:
                print(f"[PubMed] 保存文献失败: {e}")
                continue
        
        print(f"[PubMed] 成功保存 {saved_count} 篇文献到数据库")
        return saved_count
    
    def _extract_disease_tags(self, mesh_terms: List[str]) -> List[str]:
        """从MeSH主题词中提取疾病标签"""
        tags = []
        for term in mesh_terms:
            term_lower = term.lower()
            for disease in ALLOWED_DISEASES:
                if disease.lower() in term_lower:
                    tags.append(term)
                    break
        return list(set(tags))[:5]  # 最多5个标签
    
    def _infer_evidence_level(self, article: Dict) -> str:
        """根据文献类型推断证据等级"""
        # 这里简化处理，实际应根据文献类型判断
        # RCT: 1A/1B, Meta分析: 1A, 观察性研究: 2B/2C
        abstract = article.get("abstract", "").lower()
        title = article.get("title", "").lower()
        
        if "randomized controlled trial" in abstract or "rct" in title:
            return "1A"
        elif "meta-analysis" in abstract or "systematic review" in abstract:
            return "1A"
        elif "cohort" in abstract:
            return "2B"
        elif "case-control" in abstract:
            return "2C"
        else:
            return "3B"


# 全局实例
pubmed_fetcher = PubMedFetcher()