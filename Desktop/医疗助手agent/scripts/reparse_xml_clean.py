"""
重新解析已有XML文件，用新的清洗逻辑更新数据库

功能:
1. 遍历 data/en_pubmed/xml/ 下所有XML文件
2. 用改进后的 parse_pmc_xml() 重新解析（数据清洗+结构化章节）
3. 更新数据库中对应记录的 full_text（结构化JSON）、abstract、title、doi、pmid
4. 输出清洗前后对比统计
"""
import os
import sys
import json
import sqlite3
import re
from datetime import datetime

sys.path.insert(0, r"c:\Users\DELL\Desktop\医疗助手agent")
from backend.config import EN_PUBMED_DIR, DB_PATH

# 导入改进后的解析器
sys.path.insert(0, os.path.join(r"c:\Users\DELL\Desktop\医疗助手agent", "scripts"))
from crawl_pmc_fulltext import parse_pmc_xml, NOISE_TAGS

XML_DIR = os.path.join(EN_PUBMED_DIR, "xml")


def update_database(doc_id, parsed):
    """更新数据库中已有记录的full_text和其他字段"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        UPDATE table_article_meta 
        SET full_text = ?,
            abstract = ?,
            title = ?,
            doi = ?,
            pmid = ?,
            journal = ?,
            keywords = ?,
            update_time = ?
        WHERE doc_id = ?
    """, (
        parsed["full_text"],
        parsed["abstract"],
        parsed["title"],
        parsed.get("doi", ""),
        parsed.get("pmid", ""),
        parsed.get("journal", ""),
        json.dumps(parsed["keywords"], ensure_ascii=False),
        datetime.now().isoformat(),
        doc_id,
    ))

    affected = cur.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def main():
    print("=" * 70)
    print("重新解析XML文件 - 数据清洗+结构化章节")
    print(f"XML目录: {XML_DIR}")
    print(f"数据库: {DB_PATH}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    xml_files = [f for f in os.listdir(XML_DIR) if f.endswith(".xml")]
    print(f"发现 {len(xml_files)} 个XML文件\n")

    stats = {
        "total": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "old_total_chars": 0,
        "new_total_chars": 0,
        "sections_total": 0,
    }

    for i, fname in enumerate(xml_files):
        stats["total"] += 1

        # 从文件名提取PMC ID
        match = re.search(r"PMC(\d+)", fname)
        if not match:
            stats["skipped"] += 1
            continue

        pmc_num = match.group(1)
        doc_id = f"pmc_full_{pmc_num}"

        # 读取XML
        xml_path = os.path.join(XML_DIR, fname)
        with open(xml_path, "r", encoding="utf-8") as f:
            xml_text = f.read()

        # 获取旧的full_text长度（用于对比）
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT full_text FROM table_article_meta WHERE doc_id = ?", (doc_id,))
        row = cur.fetchone()
        conn.close()

        if not row:
            print(f"  [{i+1}/{len(xml_files)}] {fname} | [跳过] 数据库中无记录")
            stats["skipped"] += 1
            continue

        old_full_text = row[0] or ""
        old_len = len(old_full_text)
        stats["old_total_chars"] += old_len

        # 重新解析
        parsed = parse_pmc_xml(xml_text)
        if not parsed:
            print(f"  [{i+1}/{len(xml_files)}] {fname} | [失败] 解析失败")
            stats["failed"] += 1
            continue

        new_full_text = parsed.get("full_text", "")
        new_len = len(new_full_text)
        stats["new_total_chars"] += new_len

        num_sections = len(parsed.get("sections", []))
        stats["sections_total"] += num_sections

        # 更新数据库
        if update_database(doc_id, parsed):
            stats["updated"] += 1
            reduction = (1 - new_len / max(old_len, 1)) * 100 if old_len > 0 else 0
            print(f"  [{i+1}/{len(xml_files)}] {fname} | [更新] 旧:{old_len} 新:{new_len} 字符 ({reduction:+.0f}%) | {num_sections}章节")
        else:
            stats["failed"] += 1
            print(f"  [{i+1}/{len(xml_files)}] {fname} | [失败] 更新失败")

    # 统计报告
    print(f"\n{'=' * 70}")
    print("重新解析统计报告")
    print(f"{'=' * 70}")
    print(f"  XML文件总数: {stats['total']}")
    print(f"  成功更新: {stats['updated']}")
    print(f"  跳过: {stats['skipped']}")
    print(f"  失败: {stats['failed']}")
    print(f"  旧full_text总字符: {stats['old_total_chars']:,}")
    print(f"  新full_text总字符: {stats['new_total_chars']:,}")
    if stats['old_total_chars'] > 0:
        reduction = (1 - stats['new_total_chars'] / stats['old_total_chars']) * 100
        print(f"  噪声去除率: {reduction:.1f}%")
    print(f"  总章节数: {stats['sections_total']:,}")
    print(f"  完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
