"""
向量库重建脚本 v2
1. 清空旧ChromaDB
2. 从SQLite数据库读取所有文献（含全文）
3. 为每篇文献创建chunks（全文按章节切分，摘要作为单chunk）
4. 使用BGE-large模型生成嵌入（1024维）
5. 存入正确的ChromaDB Collection
"""
import os
import sys
import json
import shutil
import sqlite3
import time
import numpy as np
from typing import List, Dict, Any

# 设置项目路径
PROJECT_DIR = r"c:\Users\DELL\Desktop\医疗助手agent"
sys.path.insert(0, PROJECT_DIR)

# 设置模型缓存路径
os.environ["HF_HOME"] = os.path.join(PROJECT_DIR, "models")
os.environ["HF_HUB_CACHE"] = os.path.join(PROJECT_DIR, "models", "hub")
os.environ["TRANSFORMERS_CACHE"] = os.path.join(PROJECT_DIR, "models")
os.environ["HF_HUB_DISABLE_XET"] = "1"

from backend.config import (
    DB_PATH, CHROMA_DB_DIR, CHROMA_COLLECTIONS,
    EMBEDDING_MODEL_ZH, CHUNK_WINDOW, CHUNK_OVERLAP
)


def load_embedding_model():
    """加载BGE-large嵌入模型（GPU加速）"""
    import torch
    from sentence_transformers import SentenceTransformer

    # 检测GPU
    if torch.cuda.is_available():
        device = "cuda"
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"[Embedding] 使用GPU: {gpu_name} ({gpu_mem:.1f}GB)")
    else:
        device = "cpu"
        print("[Embedding] CUDA不可用，使用CPU")

    print(f"[Embedding] 加载模型: {EMBEDDING_MODEL_ZH}")
    model = SentenceTransformer(EMBEDDING_MODEL_ZH, device=device, local_files_only=True)
    dim = model.get_sentence_embedding_dimension()
    print(f"[Embedding] 模型加载完成, 维度: {dim}, 设备: {device}")
    return model, dim


def clear_chroma_db():
    """清空旧的ChromaDB"""
    if os.path.exists(CHROMA_DB_DIR):
        print(f"[ChromaDB] 清空旧数据库: {CHROMA_DB_DIR}")
        shutil.rmtree(CHROMA_DB_DIR)
        os.makedirs(CHROMA_DB_DIR, exist_ok=True)
        print("[ChromaDB] 已清空")
    else:
        os.makedirs(CHROMA_DB_DIR, exist_ok=True)
        print("[ChromaDB] 创建新目录")


def init_chroma_collections(client):
    """初始化ChromaDB Collections - 使用余弦距离"""
    collections = {}
    for coll_key, coll_config in CHROMA_COLLECTIONS.items():
        collection = client.get_or_create_collection(
            name=coll_config["name"],
            metadata={
                "description": coll_config["description"],
                "weight": str(coll_config["weight"]),
                "hnsw:space": "cosine"  # 使用余弦距离
            }
        )
        collections[coll_key] = collection
        print(f"[ChromaDB] Collection '{coll_config['name']}' 已创建, 权重={coll_config['weight']}, 距离=cosine")
    return collections


def load_all_articles() -> List[Dict[str, Any]]:
    """从SQLite数据库加载所有有摘要的文献"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 加载有摘要或有全文的文献
    cur.execute("""
        SELECT doc_id, source_type, title, publish_year, evidence_level,
               language, disease_tags, pmid, doi, abstract, keywords,
               authors, journal, full_text
        FROM table_article_meta
        WHERE (abstract IS NOT NULL AND LENGTH(abstract) > 50)
           OR (full_text IS NOT NULL AND LENGTH(full_text) > 500)
        ORDER BY source_type, publish_year DESC
    """)

    articles = []
    for row in cur.fetchall():
        article = {
            "doc_id": row["doc_id"],
            "source_type": row["source_type"],
            "title": row["title"] or "",
            "publish_year": row["publish_year"],
            "evidence_level": row["evidence_level"] or "3B",
            "language": row["language"] or "en",
            "disease_tags": json.loads(row["disease_tags"]) if row["disease_tags"] else [],
            "pmid": row["pmid"],
            "doi": row["doi"],
            "abstract": row["abstract"] or "",
            "keywords": json.loads(row["keywords"]) if row["keywords"] else [],
            "authors": json.loads(row["authors"]) if row["authors"] else [],
            "journal": row["journal"] or "",
            "full_text": row["full_text"] if "full_text" in row.keys() else None,
        }
        articles.append(article)

    conn.close()
    print(f"[Database] 加载了 {len(articles)} 篇有摘要的文献")
    return articles


def create_chunks(article: Dict[str, Any]) -> List[Dict[str, Any]]:
    """为文献创建chunks（章节级切分 + 完整可追溯元数据）

    改进点:
    1. 解析JSON格式的full_text，获取结构化章节(标题+路径+文本)
    2. 摘要作为独立chunk(chunk_index=0)，同时在正文中也保留
    3. 章节内按段落切分，超过max_chars的章节在段落边界切分
    4. 每个chunk携带完整引用元数据(journal/doi/pmid/section_path)实现可追溯
    """
    title = article["title"]
    abstract = article["abstract"]
    full_text = article.get("full_text")

    # 确定目标Collection
    source_type = article["source_type"]
    evidence_level = article["evidence_level"]

    if source_type in ("cn_guide", "cn_eupmc"):
        coll_key = "cn_guide"
    elif source_type == "pmc_fulltext":
        coll_key = "rct_meta"
    elif evidence_level.startswith("1"):
        coll_key = "rct_meta"
    else:
        coll_key = "common_study"

    max_chars = CHUNK_WINDOW * 4  # 600 token ≈ 2400 chars
    overlap_chars = CHUNK_OVERLAP * 4  # 150 token ≈ 600 chars

    # 公共元数据（所有chunk共享）
    common_meta = {
        "doc_id": article["doc_id"],
        "source_type": source_type,
        "title": title,
        "evidence_level": evidence_level,
        "language": article["language"],
        "disease_tag": article["disease_tags"],
        "publish_year": str(article["publish_year"] or ""),
        "journal": article.get("journal", "") or "",
        "doi": article.get("doi", "") or "",
        "pmid": article.get("pmid", "") or "",
        "coll_key": coll_key,
    }

    # 为pmc_fulltext文章添加xml_file用于追溯
    if source_type == "pmc_fulltext" and article.get("doc_id", "").startswith("pmc_full_"):
        pmc_num = article["doc_id"].replace("pmc_full_", "")
        common_meta["xml_file"] = f"PMC{pmc_num}.xml"

    chunks = []

    # ========== 1. 摘要独立chunk ==========
    if abstract and len(abstract) > 50:
        if article["language"] == "zh":
            abstract_text = f"标题：{title}\n\n摘要：{abstract}"
        else:
            abstract_text = f"Title: {title}\n\nAbstract: {abstract}"

        chunks.append({
            **common_meta,
            "chunk_id": f"chunk_{article['doc_id']}_0",
            "text": abstract_text[:max_chars],
            "section_title": "Abstract",
            "section_path": "Abstract",
            "chunk_index": 0,
        })

    # ========== 2. 全文章节切分 ==========
    if full_text and len(full_text) > 100:
        # 尝试解析JSON格式（新的结构化格式）
        sections = None
        try:
            if full_text.strip().startswith("["):
                sections = json.loads(full_text)
        except (json.JSONDecodeError, TypeError):
            pass

        if sections and isinstance(sections, list) and len(sections) > 0:
            # 新格式：结构化章节，按章节切分
            chunk_idx = 1  # 0是摘要
            for sec in sections:
                sec_title = sec.get("title", "") or ""
                sec_path = sec.get("path", "") or sec_title
                sec_text = sec.get("text", "")

                if not sec_text or len(sec_text) < 20:
                    continue

                # 章节内按段落切分
                paragraphs = sec_text.split("\n\n")
                current_text = ""

                for para in paragraphs:
                    para = para.strip()
                    if not para or len(para) < 10:
                        continue

                    if len(current_text) + len(para) + 2 > max_chars and current_text:
                        # 保存当前chunk
                        chunk_text = _build_chunk_text(title, sec_title, current_text, article["language"])
                        chunks.append({
                            **common_meta,
                            "chunk_id": f"chunk_{article['doc_id']}_{chunk_idx}",
                            "text": chunk_text[:max_chars],
                            "section_title": sec_title[:200],
                            "section_path": sec_path[:300],
                            "chunk_index": chunk_idx,
                        })
                        chunk_idx += 1

                        # 保留overlap
                        if len(current_text) > overlap_chars:
                            current_text = current_text[-overlap_chars:] + "\n\n" + para
                        else:
                            current_text = para
                    else:
                        current_text = (current_text + "\n\n" + para) if current_text else para

                # 保存章节最后一个chunk
                if current_text and len(current_text) > 30:
                    chunk_text = _build_chunk_text(title, sec_title, current_text, article["language"])
                    chunks.append({
                        **common_meta,
                        "chunk_id": f"chunk_{article['doc_id']}_{chunk_idx}",
                        "text": chunk_text[:max_chars],
                        "section_title": sec_title[:200],
                        "section_path": sec_path[:300],
                        "chunk_index": chunk_idx,
                    })
                    chunk_idx += 1

        else:
            # 旧格式：纯文本，按\n\n分段切分（向后兼容）
            text_sections = full_text.split("\n\n")
            current_text = ""
            chunk_idx = 1

            for section in text_sections:
                section = section.strip()
                if not section or len(section) < 20:
                    continue

                if len(current_text) + len(section) + 2 > max_chars and current_text:
                    chunk_text = _build_chunk_text(title, "", current_text, article["language"])
                    chunks.append({
                        **common_meta,
                        "chunk_id": f"chunk_{article['doc_id']}_{chunk_idx}",
                        "text": chunk_text[:max_chars],
                        "section_title": "",
                        "section_path": "",
                        "chunk_index": chunk_idx,
                    })
                    chunk_idx += 1

                    if len(current_text) > overlap_chars:
                        current_text = current_text[-overlap_chars:] + "\n\n" + section
                    else:
                        current_text = section
                else:
                    current_text = (current_text + "\n\n" + section) if current_text else section

            if current_text and len(current_text) > 30:
                chunk_text = _build_chunk_text(title, "", current_text, article["language"])
                chunks.append({
                    **common_meta,
                    "chunk_id": f"chunk_{article['doc_id']}_{chunk_idx}",
                    "text": chunk_text[:max_chars],
                    "section_title": "",
                    "section_path": "",
                    "chunk_index": chunk_idx,
                })

    # ========== 3. 无全文无摘要的兜底 ==========
    if not chunks:
        if article["language"] == "zh":
            text = f"标题：{title}\n\n摘要：{abstract}" if abstract else f"标题：{title}"
        else:
            text = f"Title: {title}\n\nAbstract: {abstract}" if abstract else f"Title: {title}"

        chunks.append({
            **common_meta,
            "chunk_id": f"chunk_{article['doc_id']}_0",
            "text": text[:max_chars],
            "section_title": "",
            "section_path": "",
            "chunk_index": 0,
        })

    # 设置total_chunks
    total = len(chunks)
    for c in chunks:
        c["total_chunks"] = total

    return chunks


def _build_chunk_text(title: str, section_title: str, body_text: str, language: str) -> str:
    """构建chunk文本，包含标题和章节标题前缀"""
    parts = []
    if language == "zh":
        parts.append(f"标题：{title}")
        if section_title:
            parts.append(f"章节：{section_title}")
    else:
        parts.append(f"Title: {title}")
        if section_title:
            parts.append(f"Section: {section_title}")
    parts.append(body_text)
    return "\n\n".join(parts)


def batch_encode(model, texts: List[str], batch_size: int = 32) -> np.ndarray:
    """批量编码文本"""
    all_embeddings = []
    total = len(texts)

    for i in range(0, total, batch_size):
        batch = texts[i:i + batch_size]
        embeddings = model.encode(
            batch,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=True
        )
        all_embeddings.append(embeddings)

        progress = min(i + batch_size, total)
        if progress % 100 == 0 or progress == total:
            print(f"  嵌入进度: {progress}/{total} ({progress/total*100:.1f}%)")

    return np.vstack(all_embeddings)


def index_chunks(collections, chunks: List[Dict[str, Any]], embeddings: np.ndarray):
    """将chunks和嵌入向量存入ChromaDB - 含完整可追溯元数据"""
    # 按Collection分组
    coll_chunks: Dict[str, List] = {}
    for i, chunk in enumerate(chunks):
        coll_key = chunk["coll_key"]
        if coll_key not in coll_chunks:
            coll_chunks[coll_key] = []
        coll_chunks[coll_key].append((chunk, embeddings[i]))

    total_indexed = 0
    for coll_key, items in coll_chunks.items():
        collection = collections[coll_key]
        if not items:
            continue

        ids = [item[0]["chunk_id"] for item in items]
        texts = [item[0]["text"] for item in items]
        metadatas = []
        for item in items:
            chunk = item[0]
            meta = {
                "doc_id": chunk["doc_id"],
                "source_type": chunk["source_type"],
                "title": chunk["title"][:500],
                "section_title": chunk.get("section_title", "")[:200],
                "section_path": chunk.get("section_path", "")[:300],
                "evidence_level": chunk["evidence_level"],
                "language": chunk["language"],
                "chunk_index": str(chunk["chunk_index"]),
                "total_chunks": str(chunk.get("total_chunks", 0)),
                "disease_tag": json.dumps(chunk["disease_tag"], ensure_ascii=False),
                "publish_year": chunk.get("publish_year", ""),
                "journal": chunk.get("journal", "")[:200],
                "doi": chunk.get("doi", "")[:100],
                "pmid": chunk.get("pmid", "")[:20],
                "xml_file": chunk.get("xml_file", "")[:100],
                "embedding_model": "bge-large-zh-v1.5"
            }
            metadatas.append(meta)

        emb_list = [item[1].tolist() for item in items]

        # 分批添加（ChromaDB限制）
        batch_size = 100
        for j in range(0, len(ids), batch_size):
            batch_ids = ids[j:j+batch_size]
            batch_texts = texts[j:j+batch_size]
            batch_metas = metadatas[j:j+batch_size]
            batch_embs = emb_list[j:j+batch_size]

            collection.add(
                ids=batch_ids,
                documents=batch_texts,
                metadatas=batch_metas,
                embeddings=batch_embs
            )

        total_indexed += len(items)
        print(f"[ChromaDB] '{coll_key}' 添加 {len(items)} 个chunks")

    return total_indexed


def main():
    print("=" * 60)
    print("向量库重建脚本")
    print("=" * 60)

    start_time = time.time()

    # Step 1: 加载嵌入模型
    print("\n[Step 1] 加载嵌入模型...")
    model, dim = load_embedding_model()

    # Step 2: 清空旧ChromaDB
    print("\n[Step 2] 清空旧ChromaDB...")
    clear_chroma_db()

    # Step 3: 初始化ChromaDB
    print("\n[Step 3] 初始化ChromaDB Collections...")
    import chromadb
    from chromadb.config import Settings
    client = chromadb.PersistentClient(
        path=CHROMA_DB_DIR,
        settings=Settings(anonymized_telemetry=False)
    )
    collections = init_chroma_collections(client)

    # Step 4: 加载所有文献
    print("\n[Step 4] 从数据库加载文献...")
    articles = load_all_articles()

    if not articles:
        print("[错误] 数据库中没有有摘要的文献！")
        return

    # Step 5: 创建chunks
    print("\n[Step 5] 创建文档chunks...")
    chunks = []
    for article in articles:
        article_chunks = create_chunks(article)
        for chunk in article_chunks:
            if chunk and len(chunk["text"]) > 50:
                chunks.append(chunk)

    print(f"  共创建 {len(chunks)} 个chunks")

    # 统计各Collection的chunk数
    coll_stats = {}
    for chunk in chunks:
        coll_key = chunk["coll_key"]
        coll_stats[coll_key] = coll_stats.get(coll_key, 0) + 1
    for k, v in coll_stats.items():
        print(f"    {k}: {v} chunks")

    # Step 6: 批量生成嵌入
    print(f"\n[Step 6] 生成嵌入向量 (共 {len(chunks)} 个)...")
    texts = [c["text"] for c in chunks]
    embeddings = batch_encode(model, texts, batch_size=64)
    print(f"  嵌入矩阵形状: {embeddings.shape}")

    # Step 7: 存入ChromaDB
    print("\n[Step 7] 存入ChromaDB...")
    total = index_chunks(collections, chunks, embeddings)
    print(f"  总共存入 {total} 个chunks")

    # Step 8: 验证
    print("\n[Step 8] 验证向量库...")
    for coll_key, collection in collections.items():
        count = collection.count()
        print(f"  {coll_key}: {count} 个向量")

    # 测试查询 - 使用BGE查询前缀
    print("\n[测试] 查询测试...")
    BGE_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
    test_queries = [
        "高血压用什么药物治疗",
        "hypertension treatment medication",
        "2型糖尿病的治疗方案",
        "心力衰竭的诊断标准",
        "atrial fibrillation anticoagulation therapy"
    ]

    for query in test_queries:
        # BGE模型查询需要加前缀
        prefixed_query = BGE_QUERY_PREFIX + query
        query_emb = model.encode([prefixed_query], normalize_embeddings=True, convert_to_numpy=True)[0]

        # 查询所有Collection，取最相关的
        best_results = []
        for coll_key, collection in collections.items():
            if collection.count() == 0:
                continue
            results = collection.query(
                query_embeddings=[query_emb.tolist()],
                n_results=3,
                include=["documents", "metadatas", "distances"]
            )
            if results["ids"] and results["ids"][0]:
                for i, chunk_id in enumerate(results["ids"][0]):
                    dist = results["distances"][0][i]
                    # 余弦距离: distance = 1 - cos_sim, 所以 sim = 1 - distance
                    similarity = max(0, 1 - dist)
                    best_results.append((similarity, coll_key, results["metadatas"][0][i]))

        # 按相似度排序
        best_results.sort(key=lambda x: x[0], reverse=True)

        print(f"\n  查询: '{query}'")
        for i, (sim, coll, meta) in enumerate(best_results[:5]):
            title = meta.get("title", "")[:50]
            sec_title = meta.get("section_title", "")[:30]
            journal = meta.get("journal", "")[:20]
            lang = meta.get("language", "?")
            level = meta.get("evidence_level", "?")
            year = meta.get("publish_year", "?")
            print(f"    [{i+1}] sim={sim:.4f} | {coll} | {lang} | {level} | {year}")
            print(f"        标题: {title}")
            if sec_title:
                print(f"        章节: {sec_title}")
            if journal:
                print(f"        期刊: {journal}")

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"向量库重建完成! 耗时: {elapsed:.1f}秒")
    print(f"总chunks: {total}")
    print(f"嵌入维度: {dim}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
