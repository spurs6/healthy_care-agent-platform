"""
外部实时检索模块 - PubMed + EuropePMC
当本地知识库检索结果不足时，实时调用外部API获取最新文献
"""
import json
import time
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime

from backend.config import (
    PUBMED_API_KEY, PUBMED_BASE_URL, ALLOWED_DISEASES
)
from backend.db_store import article_dao, ArticleMeta


class ExternalSearcher:
    """外部实时检索器 - PubMed + EuropePMC双源"""

    def __init__(self):
        self.pubmed_base = PUBMED_BASE_URL
        self.europepmc_base = "https://www.ebi.ac.uk/europepmc/webservices/rest"
        self.pubmed_headers = {"User-Agent": "OpenEvidence/1.0"}
        if PUBMED_API_KEY:
            self.pubmed_headers["api_key"] = PUBMED_API_KEY

    # ==================== PubMed 实时检索 ====================
    def search_pubmed(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        实时搜索PubMed，返回最新文献摘要

        Args:
            query: 英文搜索词
            max_results: 最多返回数量

        Returns:
            文献列表（含标题、摘要、PMID、期刊、年份等）
        """
        # Step1: esearch 获取PMID列表
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
            "sort": "relevance",
            "datetype": "pdat",
            "mindate": "2020",
            "maxdate": datetime.now().strftime("%Y/%m/%d")
        }

        try:
            resp = requests.get(
                f"{self.pubmed_base}/esearch.fcgi",
                params=search_params,
                headers=self.pubmed_headers,
                timeout=15
            )
            resp.raise_for_status()
            pmids = resp.json().get("esearchresult", {}).get("idlist", [])

            if not pmids:
                return []

            # Step2: efetch 获取文献详情
            fetch_params = {
                "db": "pubmed",
                "id": ",".join(pmids),
                "retmode": "xml"
            }

            resp = requests.get(
                f"{self.pubmed_base}/efetch.fcgi",
                params=fetch_params,
                headers=self.pubmed_headers,
                timeout=30
            )
            resp.raise_for_status()

            articles = self._parse_pubmed_xml(resp.content)
            print(f"[ExternalSearch] PubMed搜索'{query}'返回{len(articles)}篇")
            return articles

        except Exception as e:
            print(f"[ExternalSearch] PubMed搜索失败: {e}")
            return []

    def _parse_pubmed_xml(self, xml_content: bytes) -> List[Dict[str, Any]]:
        """解析PubMed XML响应"""
        import xml.etree.ElementTree as ET
        articles = []
        try:
            root = ET.fromstring(xml_content)
            for article_elem in root.findall(".//PubmedArticle"):
                try:
                    medline = article_elem.find("MedlineCitation")
                    pmid = medline.find("PMID").text if medline.find("PMID") is not None else ""

                    article = medline.find("Article")
                    if article is None:
                        continue

                    title_elem = article.find("ArticleTitle")
                    title = title_elem.text if title_elem is not None and title_elem.text else ""

                    abstract_texts = article.findall(".//Abstract/AbstractText")
                    abstract = " ".join([t.text for t in abstract_texts if t.text])

                    journal_elem = article.find("Journal/Title")
                    journal = journal_elem.text if journal_elem is not None else ""

                    year = None
                    pub_date = article.find("Journal/JournalIssue/PubDate/Year")
                    if pub_date is not None:
                        year = int(pub_date.text)

                    doi = None
                    for eloc in article.findall(".//ELocationID"):
                        if eloc.get("EIdType") == "doi":
                            doi = eloc.text
                            break

                    articles.append({
                        "source": "pubmed",
                        "pmid": pmid,
                        "title": title,
                        "abstract": abstract,
                        "journal": journal,
                        "publish_year": year,
                        "doi": doi,
                        "evidence_level": self._infer_evidence_level(abstract, title),
                        "doc_id": f"doc_ext_pubmed_{pmid}"
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"[ExternalSearch] XML解析失败: {e}")

        return articles

    # ==================== EuropePMC 实时检索 ====================
    def search_europepmc(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        实时搜索EuropePMC，支持中文文献

        Args:
            query: 搜索词（中英文均可）
            max_results: 最多返回数量

        Returns:
            文献列表
        """
        params = {
            "query": query,
            "format": "json",
            "pageSize": max_results,
            "sort": "CITED desc"
        }

        try:
            resp = requests.get(
                f"{self.europepmc_base}/search",
                params=params,
                timeout=15
            )
            resp.raise_for_status()
            results = resp.json().get("resultList", {}).get("result", [])

            articles = []
            for r in results:
                abstract = r.get("abstractText", "") or ""
                title = r.get("title", "") or ""
                pmid = r.get("pmid", "") or ""
                pmcid = r.get("pmcid", "") or ""
                doi = r.get("doi", "") or ""
                journal = r.get("journalTitle", "") or ""
                year_str = r.get("pubYear", "")
                year = int(year_str) if year_str and year_str.isdigit() else None
                lang = r.get("language", "en")

                articles.append({
                    "source": "europepmc",
                    "pmid": pmid,
                    "pmcid": pmcid,
                    "title": title,
                    "abstract": abstract,
                    "journal": journal,
                    "publish_year": year,
                    "doi": doi,
                    "language": lang,
                    "evidence_level": self._infer_evidence_level(abstract, title),
                    "doc_id": f"doc_ext_epmc_{pmid or pmcid or doi}"
                })

            print(f"[ExternalSearch] EuropePMC搜索'{query}'返回{len(articles)}篇")
            return articles

        except Exception as e:
            print(f"[ExternalSearch] EuropePMC搜索失败: {e}")
            return []

    # ==================== 双源联合检索 ====================
    def search_both(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """
        同时搜索PubMed和EuropePMC，合并去重

        Args:
            query: 搜索词
            max_results: 每个源的最大返回数

        Returns:
            {
                "articles": List[Dict],
                "total": int,
                "sources": {"pubmed": int, "europepmc": int}
            }
        """
        pubmed_results = self.search_pubmed(query, max_results)
        europepmc_results = self.search_europepmc(query, max_results)

        # 去重（按PMID或DOI）
        seen_ids = set()
        merged = []
        for article in pubmed_results + europepmc_results:
            dedup_key = article.get("pmid") or article.get("doi") or article.get("doc_id")
            if dedup_key and dedup_key not in seen_ids:
                seen_ids.add(dedup_key)
                merged.append(article)

        return {
            "articles": merged,
            "total": len(merged),
            "sources": {
                "pubmed": len(pubmed_results),
                "europepmc": len(europepmc_results)
            }
        }

    # ==================== 辅助方法 ====================
    def _infer_evidence_level(self, abstract: str, title: str) -> str:
        """根据摘要和标题推断证据等级"""
        text = (abstract + " " + title).lower()
        if any(kw in text for kw in ["meta-analysis", "systematic review", "荟萃分析"]):
            return "1A"
        elif any(kw in text for kw in ["randomized controlled trial", "rct", "随机对照"]):
            return "1B"
        elif any(kw in text for kw in ["cohort", "队列研究"]):
            return "2B"
        elif any(kw in text for kw in ["case-control", "病例对照"]):
            return "2C"
        elif any(kw in text for kw in ["guideline", "指南", "recommendation"]):
            return "1A"
        else:
            return "3B"

    def format_for_llm(self, articles: List[Dict[str, Any]]) -> str:
        """将检索结果格式化为LLM可读的文本"""
        if not articles:
            return "【外部检索未找到相关文献】"

        formatted = []
        for i, article in enumerate(articles):
            text = f"""
【外部证据片段{i+1}】
来源：{article.get('source', 'unknown')} | PMID: {article.get('pmid', 'N/A')}
标题：{article.get('title', 'N/A')}
期刊：{article.get('journal', 'N/A')} | 年份：{article.get('publish_year', 'N/A')}
证据等级：{article.get('evidence_level', '3B')}
引用ID：[{article.get('doc_id', 'ext_unknown')}]

摘要：
{article.get('abstract', '无摘要')[:800]}

---"""
            formatted.append(text)

        return '\n'.join(formatted)

    def save_to_database(self, articles: List[Dict[str, Any]]) -> int:
        """将外部检索到的文献保存到数据库（异步索引）"""
        saved = 0
        for article in articles:
            try:
                doc_id = article.get("doc_id", "")
                if not doc_id or article_dao.get_by_doc_id(doc_id):
                    continue

                # 提取疾病标签
                disease_tags = []
                text = (article.get("title", "") + " " + article.get("abstract", "")).lower()
                for disease in ALLOWED_DISEASES:
                    if disease.lower() in text:
                        disease_tags.append(disease)

                meta: ArticleMeta = {
                    "doc_id": doc_id,
                    "source_type": "pubmed" if article.get("source") == "pubmed" else "cn_eupmc",
                    "title": article.get("title", ""),
                    "publish_year": article.get("publish_year"),
                    "evidence_level": article.get("evidence_level", "3B"),
                    "language": "en" if article.get("source") == "pubmed" else "zh",
                    "disease_tags": disease_tags[:5],
                    "file_path": "",
                    "pmid": article.get("pmid"),
                    "doi": article.get("doi"),
                    "abstract": article.get("abstract"),
                    "keywords": [],
                    "authors": [],
                    "journal": article.get("journal"),
                    "create_time": datetime.now().isoformat(),
                    "update_time": datetime.now().isoformat()
                }

                if article_dao.insert(meta):
                    saved += 1
            except Exception as e:
                print(f"[ExternalSearch] 保存文献失败: {e}")
                continue

        print(f"[ExternalSearch] 保存{saved}篇文献到数据库")
        return saved


# 全局实例
external_searcher = ExternalSearcher()
