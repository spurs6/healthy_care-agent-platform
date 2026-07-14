"""
OpenEvidence 临床证据助手 - RAG检索核心模块
向量库管理、嵌入、召回、重排

v2改进:
1. GPU加速嵌入生成
2. BM25+向量混合检索
3. LLM查询重写
4. 完整可追溯元数据
"""
import os
import json
import re
import hashlib
from typing import List, Dict, Any, Optional, Tuple
import numpy as np

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer, CrossEncoder

from backend.config import (
    CHROMA_DB_DIR, CHROMA_COLLECTIONS,
    EMBEDDING_MODEL_EN, EMBEDDING_MODEL_ZH, RERANK_MODEL,
    RECALL_TOP_K, RERANK_SCORE_THRESHOLD, FINAL_SEND_LLM_TOP,
    ENABLE_TRANSFORMER_EMBEDDINGS, ENABLE_TRANSFORMER_RERANK
)
from backend.db_store.models import ChunkMeta, RetrievedChunk
from backend.rag_core.bm25_retriever import bm25_retriever
from backend.rag_core.query_rewriter import query_rewriter


class VectorStoreManager:
    """ChromaDB向量库管理器"""
    
    def __init__(self):
        self.embedding = EmbeddingModel()
        self.client = chromadb.PersistentClient(
            path=CHROMA_DB_DIR,
            settings=Settings(anonymized_telemetry=False)
        )
        self.collections = {}
        self._init_collections()
    
    def _init_collections(self):
        """初始化三个独立Collection - 使用余弦距离"""
        for coll_key, coll_config in CHROMA_COLLECTIONS.items():
            try:
                collection = self.client.get_or_create_collection(
                    name=coll_config["name"],
                    metadata={
                        "description": coll_config["description"],
                        "weight": str(coll_config["weight"]),
                        "hnsw:space": "cosine"
                    }
                )
                self.collections[coll_key] = collection
                print(f"[VectorStore] Collection '{coll_config['name']}' 已初始化，权重={coll_config['weight']}, 距离=cosine")
            except Exception as e:
                print(f"[VectorStore] 初始化Collection失败: {e}")
    
    def get_collection(self, coll_key: str) -> Optional[chromadb.Collection]:
        """获取指定Collection"""
        return self.collections.get(coll_key)
    
    def add_chunks(self, chunks: List[ChunkMeta], coll_key: str = "rct_meta", model_type: str = "zh"):
        """
        批量添加chunks到向量库
        
        Args:
            chunks: Chunk列表
            coll_key: 目标集合键
            model_type: 嵌入模型类型 ("zh" 或 "pubmed")
        """
        collection = self.get_collection(coll_key)
        if not collection:
            print(f"[VectorStore] Collection '{coll_key}' 不存在")
            return
        
        ids = [c["chunk_id"] for c in chunks]
        texts = [c["text"] for c in chunks]
        metadatas = [
            {
                "doc_id": c["doc_id"],
                "source_type": c["source_type"],
                "title": c["title"],
                "evidence_level": c["evidence_level"],
                "language": c["language"],
                "chunk_index": str(c["chunk_index"]),
                "disease_tag": json.dumps(c.get("disease_tag", []), ensure_ascii=False),
                "section_title": c.get("section_title", c.get("chapter_title", "")),
                "section_path": c.get("section_path", ""),
                "publish_year": str(c.get("publish_year", c.get("publish_date", ""))),
                "journal": c.get("journal", ""),
                "doi": c.get("doi", ""),
                "pmid": c.get("pmid", ""),
                "embedding_model": "bge-large-zh-v1.5"
            }
            for c in chunks
        ]
        embeddings = [
            self.embedding.encode_single(c["text"], c.get("language", "zh"), model_type).tolist()
            for c in chunks
        ]
        
        try:
            collection.add(
                ids=ids,
                documents=texts,
                metadatas=metadatas,
                embeddings=embeddings
            )
            print(f"[VectorStore] 成功添加 {len(chunks)} 个chunks到 '{coll_key}' (模型: {model_type})")
        except Exception as e:
            print(f"[VectorStore] 添加chunks失败: {e}")
    
    def query(self, query_text: str, coll_key: str, top_k: int = RECALL_TOP_K,
              where_filter: Dict = None, language: str = "zh", model_type: str = "zh") -> List[Dict]:
        """
        向量查询 - 使用BGE查询前缀

        Args:
            query_text: 查询文本
            coll_key: 目标集合
            top_k: 返回数量
            where_filter: 过滤条件
            language: 查询语言
            model_type: 嵌入模型类型

        Returns:
            检索结果列表
        """
        collection = self.get_collection(coll_key)
        if not collection:
            return []

        try:
            # BGE模型查询需要加前缀以获得最佳效果
            BGE_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
            prefixed_query = BGE_QUERY_PREFIX + query_text
            query_embedding = self.embedding.encode_single(
                prefixed_query, language, model_type
            ).tolist()
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )

            # 转换结果格式 - 余弦距离转换为相似度
            items = []
            if results and results["ids"]:
                for i, chunk_id in enumerate(results["ids"][0]):
                    dist = results["distances"][0][i]
                    # 余弦距离: distance = 1 - cos_sim, 所以 sim = 1 - distance
                    similarity = max(0, 1 - dist)
                    items.append({
                        "chunk_id": chunk_id,
                        "text": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": dist,
                        "similarity": similarity
                    })

            return items

        except Exception as e:
            print(f"[VectorStore] 查询失败: {e}")
            return []
    
    def delete_by_doc_id(self, doc_id: str, coll_key: str = None):
        """删除指定文档的所有chunks"""
        if coll_key:
            collection = self.get_collection(coll_key)
            if collection:
                collection.delete(where={"doc_id": doc_id})
        else:
            # 删除所有集合中的chunks
            for coll in self.collections.values():
                try:
                    coll.delete(where={"doc_id": doc_id})
                except Exception:
                    pass
    
    def get_stats(self) -> Dict[str, int]:
        """获取各Collection统计"""
        stats = {}
        for coll_key, collection in self.collections.items():
            stats[coll_key] = collection.count()
        return stats


class EmbeddingModel:
    """嵌入模型管理器 - BGE-large-zh-v1.5 (1024维, GPU加速)"""

    def __init__(self):
        self.model = None
        self._loaded = False
        self.dim = 1024
        self.model_name = EMBEDDING_MODEL_ZH
        self.device = "cpu"

        if ENABLE_TRANSFORMER_EMBEDDINGS:
            self.load_models()
        else:
            self._loaded = True

    def load_models(self):
        """加载嵌入模型（自动检测GPU）"""
        if self._loaded:
            return

        # 检测GPU
        try:
            import torch
            if torch.cuda.is_available():
                self.device = "cuda"
                gpu_name = torch.cuda.get_device_name(0)
                gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
                print(f"[Embedding] 使用GPU: {gpu_name} ({gpu_mem:.1f}GB)")
            else:
                self.device = "cpu"
                print("[Embedding] CUDA不可用，使用CPU")
        except ImportError:
            self.device = "cpu"
            print("[Embedding] PyTorch不可用，使用CPU")

        print(f"[Embedding] 开始加载嵌入模型: {self.model_name}")

        try:
            self.model = SentenceTransformer(
                self.model_name,
                device=self.device,
                local_files_only=True
            )
            self.dim = self.model.get_sentence_embedding_dimension()
            print(f"[Embedding] 模型加载完成: {self.model_name}, 维度: {self.dim}, 设备: {self.device}")
            self._loaded = True
        except Exception as e:
            print(f"[Embedding] 本地加载失败: {e}")
            print("[Embedding] 尝试在线加载...")
            try:
                self.model = SentenceTransformer(self.model_name, device=self.device)
                self.dim = self.model.get_sentence_embedding_dimension()
                print(f"[Embedding] 在线加载成功: {self.model_name}, 维度: {self.dim}")
                self._loaded = True
            except Exception as e2:
                print(f"[Embedding] 在线加载也失败: {e2}")
                raise RuntimeError(f"嵌入模型加载失败，无法继续: {e2}")

    def encode(self, texts: List[str], language: str = "en", model_type: str = "zh") -> np.ndarray:
        """
        文本向量化

        Args:
            texts: 文本列表
            language: 语言类型
            model_type: 嵌入模型类型

        Returns:
            向量矩阵
        """
        if not self._loaded:
            self.load_models()

        if self.model is None:
            raise RuntimeError("嵌入模型未加载，无法生成向量")

        return self.model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=True
        )

    def encode_single(self, text: str, language: str = "en", model_type: str = "zh") -> np.ndarray:
        """单个文本向量化"""
        return self.encode([text], language, model_type)[0]


class RerankModel:
    """Cross-Encoder重排模型（GPU加速）"""
    
    def __init__(self):
        self.model = None
        self._loaded = False
        self.backend = "lexical"
        self.device = "cpu"
        if ENABLE_TRANSFORMER_RERANK:
            self.load_model()
        else:
            self._loaded = True
    
    def load_model(self):
        """加载重排模型（自动检测GPU）"""
        if self._loaded:
            return

        # 检测GPU
        try:
            import torch
            if torch.cuda.is_available():
                self.device = "cuda"
                print(f"[Rerank] 使用GPU: {torch.cuda.get_device_name(0)}")
            else:
                self.device = "cpu"
        except ImportError:
            pass

        print(f"[Rerank] 开始加载重排模型: {RERANK_MODEL}")

        try:
            self.model = CrossEncoder(RERANK_MODEL, max_length=512, device=self.device)
            print(f"[Rerank] 重排模型加载完成: {RERANK_MODEL}, 设备: {self.device}")
            self._loaded = True
            self.backend = "transformer"
        except Exception as e:
            print(f"[Rerank] 重排模型加载失败: {e}")
            print("[Rerank] 使用基于嵌入相似度的重排方案")
            self.model = None
            self._loaded = True
            self.backend = "embedding"
    
    def rerank(self, query: str, candidates: List[Dict], 
               top_k: int = FINAL_SEND_LLM_TOP) -> List[RetrievedChunk]:
        """
        重排候选片段
        
        Args:
            query: 用户查询
            candidates: 候选片段列表
            top_k: 返回数量
        
        Returns:
            重排后的高分片段
        """
        if not self._loaded:
            self.load_model()
        
        if not candidates:
            return []

        if self.backend == "transformer" and self.model is not None:
            pairs = [(query, c["text"]) for c in candidates]
            scores = self.model.predict(pairs)
            # 归一化到0-1
            scores = (scores - scores.min()) / (scores.max() - scores.min() + 1e-8)
        else:
            # 使用嵌入余弦相似度进行重排
            scores = self._embedding_score(query, candidates)
        
        # 根据元数据调整分数（近5年文献、高证据等级加权）
        adjusted_scores = self._adjust_scores(scores, candidates)
        
        # 排序并过滤
        scored_candidates = list(zip(candidates, adjusted_scores))
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        
        # 过滤低于阈值的
        valid_chunks: List[RetrievedChunk] = []
        for candidate, score in scored_candidates:
            if score >= 0.3:  # 使用合理的阈值过滤低质量结果
                meta = candidate["metadata"]
                chunk: RetrievedChunk = {
                    "chunk_id": candidate["chunk_id"],
                    "doc_id": meta.get("doc_id", ""),
                    "text": candidate["text"],
                    "score": float(score),
                    "source_type": meta.get("source_type", ""),
                    "title": meta.get("title", ""),
                    "evidence_level": meta.get("evidence_level", ""),
                    "page": meta.get("chunk_index", meta.get("page", "1")),
                    "section_title": meta.get("section_title", ""),
                    "section_path": meta.get("section_path", ""),
                    "journal": meta.get("journal", ""),
                    "doi": meta.get("doi", ""),
                    "pmid": meta.get("pmid", ""),
                }
                valid_chunks.append(chunk)
        
        # 返回Top K
        return valid_chunks[:top_k]

    def _embedding_score(self, query: str, candidates: List[Dict]) -> np.ndarray:
        """使用嵌入余弦相似度进行重排评分"""
        texts = [c["text"] for c in candidates]
        # 查询和候选文本分别编码
        query_emb = embedding_model.encode_single(query)
        candidate_embs = embedding_model.encode(texts)

        # 计算余弦相似度（已归一化，直接点积）
        scores = candidate_embs @ query_emb
        return np.clip(scores, 0, 1)

    def _adjust_scores(self, scores: np.ndarray, candidates: List[Dict]) -> np.ndarray:
        """根据元数据调整分数"""
        adjusted = scores.copy()

        for i, candidate in enumerate(candidates):
            metadata = candidate.get("metadata", {})

            # 近5年文献加分
            try:
                year_str = metadata.get("publish_year", metadata.get("publish_date", "0"))
                if isinstance(year_str, str):
                    year = int(year_str[:4])
                else:
                    year = int(year_str)
                if year >= 2020:  # 近5年
                    adjusted[i] += 0.03
                if year >= 2023:  # 近2年
                    adjusted[i] += 0.02
            except (ValueError, TypeError):
                pass

            # 高证据等级加分
            evidence_level = metadata.get("evidence_level", "")
            if "1A" in evidence_level or "ⅠA" in evidence_level:
                adjusted[i] += 0.05
            elif "1B" in evidence_level or "ⅠB" in evidence_level:
                adjusted[i] += 0.03

            # 中文指南加分（最高优先级）
            if metadata.get("source_type") in ("cn_guide", "cn_eupmc"):
                adjusted[i] += 0.05

        # 归一化到0-1范围
        adjusted = np.clip(adjusted, 0, 1)

        return adjusted


class RAGRetriever:
    """RAG检索完整链路"""
    
    def __init__(self):
        self.vector_store = vector_store
        self.embedding = embedding_model
        self.rerank = rerank_model
    
    def retrieve(self, query: str, language: str = "zh", model_type: str = "zh") -> Tuple[List[RetrievedChunk], bool]:
        """
        完整检索流程（v2: 查询重写 + 向量+BM25混合检索 + 重排）
        
        Args:
            query: 用户查询
            language: 查询语言
            model_type: 嵌入模型类型 ("zh" 或 "pubmed")
        
        Returns:
            (检索结果列表, 是否有有效证据)
        """
        print(f"[RAG] 开始检索: {query[:50]}... (模型: {model_type})")

        stats = self.vector_store.get_stats()
        if sum(stats.values()) == 0:
            print("[RAG] 向量库为空，跳过检索")
            return [], False

        # Step 1: 查询重写（同义词扩展 + LLM重写）
        enhanced_query, expanded_queries = query_rewriter.rewrite(query)
        if len(expanded_queries) > 1:
            print(f"[RAG] 查询重写: 原始='{query[:30]}' → {len(expanded_queries)}个扩展查询")
        
        # Step 2: 向量多路召回（使用增强查询 + 扩展查询）
        vec_candidates = []
        seen_chunk_ids = set()
        
        for q in expanded_queries:
            q_results = self._vector_recall(q, language, model_type)
            for r in q_results:
                if r["chunk_id"] not in seen_chunk_ids:
                    seen_chunk_ids.add(r["chunk_id"])
                    vec_candidates.append(r)

        # Step 3: BM25关键词召回
        bm25_candidates = bm25_retriever.search(enhanced_query, top_k=RECALL_TOP_K * 2)
        print(f"[RAG] 向量召回: {len(vec_candidates)} | BM25召回: {len(bm25_candidates)}")

        # Step 4: 合并去重
        merged = self._merge_candidates(vec_candidates, bm25_candidates)

        if not merged:
            print("[RAG] 未检索到任何候选片段")
            return [], False

        print(f"[RAG] 合并候选片段数: {len(merged)}")

        # Step 5: Cross-Encoder重排
        reranked = self.rerank.rerank(query, merged)

        # Step 6: 检查是否有有效证据
        has_evidence = len(reranked) > 0

        if not has_evidence:
            print("[RAG] 无有效证据（所有片段低于阈值）")

        print(f"[RAG] 检索完成，有效证据数: {len(reranked)}")
        return reranked, has_evidence
    
    def _vector_recall(self, query: str, language: str, model_type: str = "zh") -> List[Dict]:
        """向量多路召回
        
        Args:
            query: 查询文本
            language: 语言类型
            model_type: 嵌入模型类型
        """
        candidates = []
        
        # 检索所有Collection
        for coll_key, weight in [(k, v["weight"]) for k, v in CHROMA_COLLECTIONS.items()]:
            results = self.vector_store.query(
                query_text=query,
                coll_key=coll_key,
                top_k=RECALL_TOP_K,
                model_type=model_type
            )
            
            # 添加权重信息
            for r in results:
                r["weight"] = weight
                candidates.append(r)
        
        return candidates
    
    def _keyword_recall(self, query: str, model_type: str = "zh") -> List[Dict]:
        """关键词实体召回
        
        Args:
            query: 查询文本
            model_type: 嵌入模型类型
        """
        # 简化实现：使用疾病关键词过滤
        # 实际应使用医学实体识别模型
        
        keywords = []
        for disease in ["高血压", "糖尿病", "高血脂", "hypertension", "diabetes", "cardiovascular"]:
            if disease.lower() in query.lower():
                keywords.append(disease)
        
        if not keywords:
            return []
        
        candidates = []
        for coll_key in self.vector_store.collections.keys():
            collection = self.vector_store.get_collection(coll_key)
            if collection:
                # 构建过滤条件
                for kw in keywords:
                    try:
                        results = collection.query(
                            query_embeddings=[self.vector_store.embedding.encode_single(kw, "zh", model_type).tolist()],
                            n_results=5,
                            where={"disease_tag": kw},
                            include=["documents", "metadatas"]
                        )
                        for i, chunk_id in enumerate(results["ids"][0]):
                            candidates.append({
                                "chunk_id": chunk_id,
                                "text": results["documents"][0][i],
                                "metadata": results["metadatas"][0][i],
                                "distance": 0.5  # 关键词匹配默认分数
                            })
                    except Exception:
                        pass
        
        return candidates
    
    def _merge_candidates(self, vec_candidates: List[Dict], 
                          keyword_candidates: List[Dict]) -> List[Dict]:
        """合并并去重候选"""
        seen_ids = set()
        merged = []
        
        # 向量召回优先
        for c in vec_candidates:
            if c["chunk_id"] not in seen_ids:
                seen_ids.add(c["chunk_id"])
                merged.append(c)
        
        # 添加关键词召回
        for c in keyword_candidates:
            if c["chunk_id"] not in seen_ids:
                seen_ids.add(c["chunk_id"])
                merged.append(c)
        
        return merged
    
    def index_document(self, chunks: List[ChunkMeta]):
        """将文档chunks索引到向量库"""
        # 根据source_type分Collection
        cn_chunks = []
        rct_chunks = []
        common_chunks = []
        
        for chunk in chunks:
            source_type = chunk["source_type"]
            if source_type == "cn_guide":
                cn_chunks.append(chunk)
            elif chunk.get("evidence_level", "").startswith("1") or "RCT" in chunk.get("chapter_title", ""):
                rct_chunks.append(chunk)
            else:
                common_chunks.append(chunk)
        
        # 添加到对应Collection
        if cn_chunks:
            self.vector_store.add_chunks(cn_chunks, "cn_guide")
        if rct_chunks:
            self.vector_store.add_chunks(rct_chunks, "rct_meta")
        if common_chunks:
            self.vector_store.add_chunks(common_chunks, "common_study")


# 全局实例
vector_store = VectorStoreManager()
embedding_model = EmbeddingModel()
rerank_model = RerankModel()
rag_retriever = RAGRetriever()
