"""
BM25关键词检索模块 - 用于混合检索

从SQLite数据库直接进行BM25关键词检索，
与向量检索结果融合，提升召回率
"""
import os
import re
import math
import sqlite3
from typing import List, Dict, Any, Set
from collections import Counter, defaultdict

from backend.config import DB_PATH


class BM25Retriever:
    """BM25关键词检索器"""

    def __init__(self):
        self.documents: List[Dict[str, Any]] = []
        self.doc_tokens: List[List[str]] = []
        self.tf: List[Counter] = []
        self.idf: Dict[str, float] = {}
        self.avg_doc_len: float = 0
        self.doc_count: int = 0
        self._loaded = False

    def _tokenize(self, text: str) -> List[str]:
        """分词：中文按字符+双字符，英文按单词"""
        tokens = []
        # 英文单词
        en_words = re.findall(r'[a-zA-Z]{2,}', text.lower())
        tokens.extend(en_words)
        # 中文双字符滑动窗口
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        for i in range(len(chinese_chars) - 1):
            tokens.append(chinese_chars[i] + chinese_chars[i + 1])
        # 中文单字符
        tokens.extend(chinese_chars)
        return tokens

    def load_from_db(self):
        """从SQLite数据库加载所有文档用于BM25索引"""
        if self._loaded:
            return

        print("[BM25] 正在从数据库加载文档...")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("""
            SELECT doc_id, title, abstract, full_text, source_type,
                   evidence_level, language, disease_tags, publish_year,
                   journal, doi, pmid
            FROM table_article_meta
            WHERE (abstract IS NOT NULL AND LENGTH(abstract) > 50)
               OR (full_text IS NOT NULL AND LENGTH(full_text) > 100)
        """)

        docs = []
        for row in cur.fetchall():
            title = row["title"] or ""
            abstract = row["abstract"] or ""
            full_text = row["full_text"] or ""

            # 构建可检索文本
            searchable_text = f"{title} {abstract}"
            if full_text and full_text.startswith("["):
                # JSON格式全文，提取章节文本
                import json
                try:
                    sections = json.loads(full_text)
                    for sec in sections:
                        searchable_text += " " + sec.get("text", "")
                except (json.JSONDecodeError, TypeError):
                    pass
            elif full_text:
                searchable_text += " " + full_text[:5000]  # 限制长度

            docs.append({
                "doc_id": row["doc_id"],
                "text": searchable_text[:10000],  # 限制总长度
                "title": title,
                "source_type": row["source_type"],
                "evidence_level": row["evidence_level"] or "3B",
                "language": row["language"] or "en",
                "disease_tags": row["disease_tags"] or "[]",
                "publish_year": row["publish_year"],
                "journal": row["journal"] or "",
                "doi": row["doi"] or "",
                "pmid": row["pmid"] or "",
            })

        conn.close()

        self.documents = docs
        self.doc_tokens = [self._tokenize(doc["text"]) for doc in docs]
        self.tf = [Counter(tokens) for tokens in self.doc_tokens]
        self.doc_count = len(docs)
        self.avg_doc_len = sum(len(t) for t in self.doc_tokens) / max(self.doc_count, 1)

        # 计算IDF
        df = defaultdict(int)
        for tokens in self.doc_tokens:
            for token in set(tokens):
                df[token] += 1

        for token, freq in df.items():
            self.idf[token] = math.log((self.doc_count - freq + 0.5) / (freq + 0.5) + 1)

        self._loaded = True
        print(f"[BM25] 加载完成: {self.doc_count} 篇文档, 平均长度: {self.avg_doc_len:.0f} tokens")

    def search(self, query: str, top_k: int = 20) -> List[Dict[str, Any]]:
        """BM25检索

        Args:
            query: 查询文本
            top_k: 返回数量

        Returns:
            检索结果列表，按BM25分数排序
        """
        if not self._loaded:
            self.load_from_db()

        if self.doc_count == 0:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # BM25参数
        k1 = 1.5
        b = 0.75

        scores = []
        for i, doc_tf in enumerate(self.tf):
            score = 0.0
            doc_len = len(self.doc_tokens[i])
            for token in query_tokens:
                if token not in self.idf:
                    continue
                tf = doc_tf.get(token, 0)
                if tf == 0:
                    continue
                idf = self.idf[token]
                # BM25公式
                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * doc_len / self.avg_doc_len)
                score += idf * numerator / denominator

            if score > 0:
                doc = self.documents[i]
                # 归一化BM25分数到0-1范围
                normalized_score = min(1.0, score / 30.0)  # 经验值
                scores.append((i, normalized_score, doc))

        # 按分数排序
        scores.sort(key=lambda x: x[1], reverse=True)

        # 返回top_k结果
        results = []
        for idx, score, doc in scores[:top_k]:
            results.append({
                "chunk_id": f"bm25_{doc['doc_id']}",
                "doc_id": doc["doc_id"],
                "text": doc["text"][:2400],  # 截断为chunk大小
                "metadata": {
                    "doc_id": doc["doc_id"],
                    "source_type": doc["source_type"],
                    "title": doc["title"],
                    "evidence_level": doc["evidence_level"],
                    "language": doc["language"],
                    "disease_tag": doc["disease_tags"],
                    "publish_year": str(doc["publish_year"] or ""),
                    "journal": doc["journal"],
                    "doi": doc["doi"],
                    "pmid": doc["pmid"],
                    "section_title": "",
                    "section_path": "",
                },
                "distance": 1 - score,
                "similarity": score,
            })

        return results


# 全局实例
bm25_retriever = BM25Retriever()
