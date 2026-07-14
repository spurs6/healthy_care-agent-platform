#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中文医学文献爬虫脚本（EuropePMC 数据源）
==========================================
功能：
  1. 从 EuropePMC 搜索中文医学开放获取文献
  2. 搜索8个疾病关键词，每个50篇，预计获取约300-400篇
  3. 过滤条件：FILTER=LANG:zh AND OPEN_ACCESS:y
  4. 提取 title, abstract, authors, journal, pubYear, doi, pmid, pmcid
  5. 存入 SQLite 数据库 table_article_meta 表
  6. doc_id 格式：cn_eupmc_{pmid或pmcid}
  7. source_type="cn_eupmc", language="zh", evidence_level="2A"
  8. 3秒请求间隔，避免被ban

数据库表：table_article_meta
字段：doc_id, source_type, title, publish_year, evidence_level, language,
      disease_tags, file_path, pmid, doi, abstract, keywords, authors,
      journal, create_time, update_time, full_text
"""

import os
import re
import sys
import time
import json
import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Set
from html import unescape

import requests


# ==================== 路径配置 ====================
PROJECT_ROOT = r"c:\Users\DELL\Desktop\医疗助手agent"
DB_PATH = os.path.join(PROJECT_ROOT, "data", "clinical_kb.db")

# ==================== API 配置 ====================
EUROPEPMC_BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
PAGE_SIZE = 50            # 每个关键词获取数量
REQUEST_INTERVAL = 3      # 请求间隔（秒），避免被ban
REQUEST_TIMEOUT = 30      # 请求超时（秒）
MAX_RETRIES = 3           # 最大重试次数
RETRY_BACKOFF = 2         # 指数退避基数（秒）

# HTTP 请求头
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "OpenEvidence-CNCrawler/1.0"
    ),
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate",
}

# ==================== 疾病关键词配置（8个）====================
DISEASE_KEYWORDS: List[Dict[str, str]] = [
    {"keyword": "高血压",   "tag": "高血压"},
    {"keyword": "糖尿病",   "tag": "糖尿病"},
    {"keyword": "心力衰竭", "tag": "心力衰竭"},
    {"keyword": "心房颤动", "tag": "心房颤动"},
    {"keyword": "高血脂",   "tag": "高血脂"},
    {"keyword": "脑卒中",   "tag": "脑卒中"},
    {"keyword": "冠心病",   "tag": "冠心病"},
    {"keyword": "心律失常", "tag": "心律失常"},
]

# ==================== 日志配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(PROJECT_ROOT, "scripts", "crawl_cn_literature.log"),
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("CnLiteratureCrawler")


# ==================== 工具函数 ====================
def strip_html_tags(text: str) -> str:
    """去除HTML标签并清理空白"""
    if not text:
        return ""
    # 去除 HTML 标签
    clean = re.sub(r"<[^>]+>", " ", text)
    # HTML 实体解码
    clean = unescape(clean)
    # 合并多余空白
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def now_iso() -> str:
    """当前时间ISO格式"""
    return datetime.now().isoformat()


def now_str() -> str:
    """当前时间可读格式"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def print_section(title: str):
    """打印分隔标题"""
    line = "=" * 64
    logger.info(line)
    logger.info(f"  {title}")
    logger.info(line)


def retry_request(url: str, params: dict, max_retries: int = MAX_RETRIES,
                  timeout: int = REQUEST_TIMEOUT) -> Optional[requests.Response]:
    """带指数退避重试的 HTTP GET 请求"""
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.exceptions.Timeout:
            logger.warning(f"    请求超时（第{attempt}/{max_retries}次），{RETRY_BACKOFF ** attempt}秒后重试...")
            time.sleep(RETRY_BACKOFF ** attempt)
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"    网络连接异常（第{attempt}/{max_retries}次）: {e}")
            time.sleep(RETRY_BACKOFF ** attempt)
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else "N/A"
            if status_code in (429, 503):
                wait = RETRY_BACKOFF ** attempt * 2
                logger.warning(f"    服务限流({status_code})（第{attempt}/{max_retries}次），{wait}秒后重试...")
                time.sleep(wait)
            else:
                logger.error(f"    HTTP错误({status_code})（第{attempt}/{max_retries}次）: {e}")
                time.sleep(RETRY_BACKOFF ** attempt)
        except requests.exceptions.RequestException as e:
            logger.warning(f"    请求异常（第{attempt}/{max_retries}次）: {e}")
            time.sleep(RETRY_BACKOFF ** attempt)

    logger.error(f"    已达最大重试次数({max_retries})，放弃此请求")
    return None


# ==================== 数据库操作 ====================
def get_db_connection() -> sqlite3.Connection:
    """获取 SQLite 数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_existing_doc_ids() -> Set[str]:
    """获取数据库中已存在的所有 doc_id（用于去重）"""
    existing = set()
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT doc_id FROM table_article_meta")
            for row in cursor.fetchall():
                existing.add(row["doc_id"])
    except sqlite3.Error as e:
        logger.error(f"获取已有doc_id失败: {e}")
    return existing


def get_existing_eupmc_ids() -> Set[str]:
    """获取数据库中已存在的 cn_eupmc 类型的 pmid/pmcid（用于二次去重）"""
    existing = set()
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT pmid, doi FROM table_article_meta WHERE source_type = 'cn_eupmc'"
            )
            for row in cursor.fetchall():
                if row["pmid"]:
                    existing.add(f"pmid:{row['pmid']}")
                if row["doi"]:
                    existing.add(f"doi:{row['doi']}")
    except sqlite3.Error as e:
        logger.error(f"获取已有eupmc记录失败: {e}")
    return existing


def insert_article(article: Dict[str, Any]) -> bool:
    """
    插入单篇文献到 table_article_meta 表。
    使用 INSERT OR REPLACE 实现幂等写入。
    """
    sql = """
        INSERT OR REPLACE INTO table_article_meta
        (doc_id, source_type, title, publish_year, evidence_level, language,
         disease_tags, file_path, pmid, doi, abstract, keywords, authors,
         journal, create_time, update_time, full_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    values = (
        article["doc_id"],
        article["source_type"],
        article["title"],
        article.get("publish_year"),
        article.get("evidence_level", ""),
        article.get("language", "zh"),
        json.dumps(article.get("disease_tags", []), ensure_ascii=False),
        article.get("file_path", ""),
        article.get("pmid"),
        article.get("doi"),
        article.get("abstract"),
        json.dumps(article.get("keywords", []), ensure_ascii=False),
        json.dumps(article.get("authors", []), ensure_ascii=False),
        article.get("journal"),
        article.get("create_time", now_iso()),
        article.get("update_time", now_iso()),
        article.get("full_text", ""),
    )
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, values)
            conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error(f"    插入数据库失败 [{article.get('doc_id')}]: {e}")
        return False


# ==================== EuropePMC 爬虫核心 ====================
def build_search_params(keyword: str) -> dict:
    """构建 EuropePMC 搜索参数"""
    return {
        "query": keyword,
        "resultType": "core",
        "format": "json",
        "pageSize": PAGE_SIZE,
        "filter": "LANG:zh AND OPEN_ACCESS:y",
    }


def extract_pmid(result: Dict) -> Optional[str]:
    """提取 PMID"""
    pmid = result.get("pmid")
    if pmid:
        return str(pmid).strip()
    return None


def extract_pmcid(result: Dict) -> Optional[str]:
    """提取 PMCID"""
    pmcid = result.get("pmcid")
    if pmcid:
        return str(pmcid).strip()
    return None


def extract_authors(result: Dict) -> List[str]:
    """提取作者列表"""
    authors = []
    author_list = result.get("authorList", {}).get("author", [])
    if isinstance(author_list, list):
        for a in author_list:
            full_name = a.get("fullName", "")
            if full_name:
                authors.append(full_name.strip())
    return authors


def extract_journal(result: Dict) -> Optional[str]:
    """提取期刊名称"""
    journal_info = result.get("journalInfo", {})
    journal = journal_info.get("journal", {})
    title = journal.get("title", "")
    if title:
        return title.strip()
    # 退而求其次使用 journalTitle 字段
    journal_title = result.get("journalTitle", "")
    if journal_title:
        return journal_title.strip()
    return None


def extract_pub_year(result: Dict) -> Optional[int]:
    """提取发表年份"""
    pub_year_str = result.get("pubYear", "")
    if pub_year_str:
        try:
            return int(pub_year_str)
        except (ValueError, TypeError):
            pass
    # 从 journalInfo 中提取
    journal_info = result.get("journalInfo", {})
    year_of_pub = journal_info.get("yearOfPublication")
    if year_of_pub:
        try:
            return int(year_of_pub)
        except (ValueError, TypeError):
            pass
    return None


def extract_keywords(result: Dict) -> List[str]:
    """提取关键词列表"""
    keywords = []
    keyword_list = result.get("keywordList", {}).get("keyword", [])
    if isinstance(keyword_list, list):
        for kw in keyword_list:
            if kw and isinstance(kw, str):
                keywords.append(kw.strip())
    return keywords


def extract_full_text_url(result: Dict) -> str:
    """
    提取开放获取的 PDF 链接。
    优先选择 documentStyle 为 pdf 的链接，
    其次选择 availability 为 Open access 的链接。
    """
    full_text_urls = result.get("fullTextUrlList", {}).get("fullTextUrl", [])
    if not isinstance(full_text_urls, list):
        return ""

    # 优先：documentStyle == pdf
    for url_info in full_text_urls:
        if url_info.get("documentStyle") == "pdf":
            url = url_info.get("url", "")
            if url:
                return url.strip()

    # 次选：availability == Open access
    for url_info in full_text_urls:
        availability = (url_info.get("availability") or "").lower()
        if "open access" in availability or availability == "open access":
            url = url_info.get("url", "")
            if url:
                return url.strip()

    # 最后：取第一个可用链接
    if full_text_urls:
        url = full_text_urls[0].get("url", "")
        if url:
            return url.strip()

    return ""


def parse_article(result: Dict, disease_tag: str) -> Optional[Dict[str, Any]]:
    """
    解析单篇 EuropePMC 搜索结果，提取结构化字段。
    返回符合 table_article_meta 表结构的字典，若不符合要求返回 None。
    """
    # 提取标题
    title = strip_html_tags(result.get("title", ""))
    if not title:
        return None

    # 提取摘要
    abstract = strip_html_tags(result.get("abstractText", ""))
    if not abstract or len(abstract.strip()) < 30:
        return None

    # 提取 pmid 和 pmcid
    pmid = extract_pmid(result)
    pmcid = extract_pmcid(result)

    # doc_id 生成：优先使用 pmid，其次 pmcid
    uid = pmid or pmcid
    if not uid:
        logger.warning(f"    跳过: 无 pmid 和 pmcid 的文献 - {title[:40]}...")
        return None

    doc_id = f"cn_eupmc_{uid}"

    # 提取 DOI
    doi = result.get("doi")
    if doi:
        doi = doi.strip()

    # 提取发表年份
    pub_year = extract_pub_year(result)

    # 提取作者
    authors = extract_authors(result)

    # 提取期刊
    journal = extract_journal(result)

    # 提取关键词
    keywords = extract_keywords(result)

    # 提取全文URL（开放获取PDF链接）
    full_text_url = extract_full_text_url(result)

    return {
        "doc_id": doc_id,
        "source_type": "cn_eupmc",
        "title": title,
        "publish_year": pub_year,
        "evidence_level": "2A",
        "language": "zh",
        "disease_tags": [disease_tag],
        "file_path": "",
        "pmid": pmid,
        "doi": doi,
        "abstract": abstract,
        "keywords": keywords,
        "authors": authors,
        "journal": journal,
        "full_text": full_text_url,  # 开放获取PDF链接，后续手动补充全文
        "create_time": now_iso(),
        "update_time": now_iso(),
        # 额外信息（不入库，用于日志）
        "_pmcid": pmcid,
    }


def crawl_keyword(keyword: str, disease_tag: str,
                  existing_doc_ids: Set[str],
                  existing_ids: Set[str]) -> List[Dict[str, Any]]:
    """
    爬取单个关键词的文献。
    返回解析后的文献列表。
    """
    logger.info(f"  开始搜索关键词: '{keyword}' (标签: {disease_tag})")

    params = build_search_params(keyword)
    resp = retry_request(EUROPEPMC_BASE_URL, params)
    if resp is None:
        logger.error(f"  关键词 '{keyword}' 搜索请求失败，跳过")
        return []

    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        logger.error(f"  关键词 '{keyword}' JSON解析失败: {e}")
        return []

    hit_count = data.get("hitCount", 0)
    results = data.get("resultList", {}).get("result", [])
    logger.info(f"  关键词 '{keyword}': 总命中 {hit_count} 篇，本次返回 {len(results)} 篇")

    articles = []
    skip_count = 0
    dup_count = 0

    for idx, result in enumerate(results, 1):
        article = parse_article(result, disease_tag)
        if article is None:
            skip_count += 1
            continue

        doc_id = article["doc_id"]

        # 去重检查1：doc_id 已存在
        if doc_id in existing_doc_ids:
            dup_count += 1
            continue

        # 去重检查2：pmid 或 doi 已存在（跨关键词去重）
        dedup_key = None
        if article.get("pmid"):
            dedup_key = f"pmid:{article['pmid']}"
        elif article.get("doi"):
            dedup_key = f"doi:{article['doi']}"
        if dedup_key and dedup_key in existing_ids:
            dup_count += 1
            continue

        # 通过检查，添加到结果列表
        articles.append(article)
        existing_doc_ids.add(doc_id)
        if dedup_key:
            existing_ids.add(dedup_key)

        # 进度日志（每10篇输出一次）
        if idx % 10 == 0 or idx == len(results):
            logger.info(f"    进度: {idx}/{len(results)} - 有效 {len(articles)} 篇")

    logger.info(
        f"  关键词 '{keyword}' 完成: 有效 {len(articles)} 篇, "
        f"跳过(无摘要/无ID) {skip_count} 篇, 重复 {dup_count} 篇"
    )
    return articles


def crawl_all_keywords() -> List[Dict[str, Any]]:
    """爬取所有疾病关键词的中文文献"""
    # 获取数据库中已有的 doc_id 和 eupmc 记录（用于去重）
    existing_doc_ids = get_existing_doc_ids()
    existing_ids = get_existing_eupmc_ids()
    logger.info(f"  数据库已有 doc_id 数量: {len(existing_doc_ids)}")
    logger.info(f"  数据库已有 cn_eupmc 记录数量: {len(existing_ids)}")

    all_articles: List[Dict[str, Any]] = []
    keyword_stats: List[Dict[str, int]] = []

    for i, disease in enumerate(DISEASE_KEYWORDS, 1):
        keyword = disease["keyword"]
        tag = disease["tag"]
        logger.info(f"\n  [{i}/{len(DISEASE_KEYWORDS)}] 处理关键词: {keyword}")

        articles = crawl_keyword(keyword, tag, existing_doc_ids, existing_ids)

        # 逐篇入库
        saved = 0
        failed = 0
        for article in articles:
            if insert_article(article):
                saved += 1
                all_articles.append(article)
            else:
                failed += 1

        keyword_stats.append({
            "keyword": keyword,
            "total_results": len(articles),
            "saved": saved,
            "failed": failed,
        })
        logger.info(f"  关键词 '{keyword}': 入库成功 {saved} 篇, 失败 {failed} 篇")

        # 请求间隔（最后一个关键词不需要等待）
        if i < len(DISEASE_KEYWORDS):
            logger.info(f"  等待 {REQUEST_INTERVAL} 秒（请求间隔）...")
            time.sleep(REQUEST_INTERVAL)

    return all_articles, keyword_stats


# ==================== 统计报告 ====================
def get_db_stats() -> Dict[str, int]:
    """获取数据库统计信息"""
    stats = {"total": 0, "cn_eupmc": 0, "cn_eupmc_zh": 0}
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM table_article_meta")
            stats["total"] = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM table_article_meta WHERE source_type = 'cn_eupmc'"
            )
            stats["cn_eupmc"] = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM table_article_meta "
                "WHERE source_type = 'cn_eupmc' AND language = 'zh'"
            )
            stats["cn_eupmc_zh"] = cursor.fetchone()[0]
    except sqlite3.Error as e:
        logger.error(f"获取数据库统计失败: {e}")
    return stats


def print_report(all_articles: List[Dict], keyword_stats: List[Dict],
                 db_before: Dict, db_after: Dict):
    """输出最终统计报告"""
    print_section("爬取统计报告")

    # 关键词维度统计
    logger.info("  【按关键词统计】")
    logger.info(f"  {'关键词':<10} {'有效篇数':>8} {'入库成功':>8} {'入库失败':>8}")
    logger.info(f"  {'-' * 40}")
    total_valid = 0
    total_saved = 0
    total_failed = 0
    for s in keyword_stats:
        logger.info(
            f"  {s['keyword']:<10} {s['total_results']:>8} "
            f"{s['saved']:>8} {s['failed']:>8}"
        )
        total_valid += s["total_results"]
        total_saved += s["saved"]
        total_failed += s["failed"]
    logger.info(f"  {'-' * 40}")
    logger.info(
        f"  {'合计':<10} {total_valid:>8} {total_saved:>8} {total_failed:>8}"
    )

    # 数据库变化统计
    logger.info("")
    logger.info("  【数据库变化】")
    logger.info(f"  爬取前数据库总文献数:   {db_before['total']}")
    logger.info(f"  爬取前cn_eupmc文献数:   {db_before['cn_eupmc']}")
    logger.info(f"  爬取后数据库总文献数:   {db_after['total']}")
    logger.info(f"  爬取后cn_eupmc文献数:   {db_after['cn_eupmc']}")
    logger.info(f"  本次新增 cn_eupmc:     {db_after['cn_eupmc'] - db_before['cn_eupmc']} 篇")

    # 数据质量统计
    logger.info("")
    logger.info("  【数据质量统计】")
    has_abstract = sum(1 for a in all_articles if a.get("abstract"))
    has_doi = sum(1 for a in all_articles if a.get("doi"))
    has_pmid = sum(1 for a in all_articles if a.get("pmid"))
    has_full_text = sum(1 for a in all_articles if a.get("full_text"))
    has_authors = sum(1 for a in all_articles if a.get("authors"))
    has_journal = sum(1 for a in all_articles if a.get("journal"))

    total = len(all_articles) if all_articles else 1
    logger.info(f"  总入库文献数:           {len(all_articles)}")
    logger.info(f"  含摘要:                 {has_abstract} ({has_abstract*100//total}%)")
    logger.info(f"  含DOI:                  {has_doi} ({has_doi*100//total}%)")
    logger.info(f"  含PMID:                 {has_pmid} ({has_pmid*100//total}%)")
    logger.info(f"  含全文PDF链接:          {has_full_text} ({has_full_text*100//total}%)")
    logger.info(f"  含作者信息:             {has_authors} ({has_authors*100//total}%)")
    logger.info(f"  含期刊信息:             {has_journal} ({has_journal*100//total}%)")

    # 年份分布
    logger.info("")
    logger.info("  【年份分布（前10）】")
    year_dist: Dict[int, int] = {}
    for a in all_articles:
        year = a.get("publish_year")
        if year:
            year_dist[year] = year_dist.get(year, 0) + 1
    for year in sorted(year_dist.keys(), reverse=True)[:10]:
        logger.info(f"    {year}: {year_dist[year]} 篇")

    # 目标检查
    logger.info("")
    target = 300
    if db_after["cn_eupmc"] >= target:
        logger.info(
            f"  >>> 目标达成: cn_eupmc 文献已达 {db_after['cn_eupmc']} 篇 "
            f"(目标 >= {target}) <<<"
        )
    else:
        logger.info(
            f"  >>> 未达标: cn_eupmc 文献 {db_after['cn_eupmc']} 篇 "
            f"(目标 >= {target})，差 {target - db_after['cn_eupmc']} 篇 <<<"
        )


# ==================== 主函数 ====================
def main():
    print_section("中文医学文献爬虫 - EuropePMC")
    logger.info(f"  脚本路径:     {os.path.abspath(__file__)}")
    logger.info(f"  数据库路径:   {DB_PATH}")
    logger.info(f"  API地址:      {EUROPEPMC_BASE_URL}")
    logger.info(f"  请求间隔:     {REQUEST_INTERVAL} 秒")
    logger.info(f"  每词获取量:   {PAGE_SIZE} 篇")
    logger.info(f"  关键词数量:   {len(DISEASE_KEYWORDS)} 个")
    logger.info(f"  开始时间:     {now_str()}")
    logger.info(f"  疾病关键词列表:")
    for i, d in enumerate(DISEASE_KEYWORDS, 1):
        logger.info(f"    {i}. {d['keyword']} -> {d['tag']}")

    # 检查数据库文件是否存在
    if not os.path.exists(DB_PATH):
        logger.error(f"  数据库文件不存在: {DB_PATH}")
        logger.error("  请先运行 init_database.py 初始化数据库")
        sys.exit(1)

    # 获取爬取前的数据库状态
    db_before = get_db_stats()
    logger.info(f"  爬取前数据库状态: 总文献 {db_before['total']} 篇, "
                f"cn_eupmc {db_before['cn_eupmc']} 篇")

    # 开始爬取
    print_section("开始爬取中文医学文献")
    all_articles, keyword_stats = crawl_all_keywords()

    # 获取爬取后的数据库状态
    db_after = get_db_stats()

    # 输出统计报告
    print_report(all_articles, keyword_stats, db_before, db_after)

    logger.info(f"\n  结束时间: {now_str()}")
    print_section("脚本执行完毕")


if __name__ == "__main__":
    main()
