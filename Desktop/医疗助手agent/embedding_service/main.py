"""
本地嵌入服务 - 使用BGE-large-zh-v1.5模型
- BAAI/bge-large-zh-v1.5 (中英文通用，1024维)
"""
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import numpy as np
import uvicorn
import os
from sentence_transformers import SentenceTransformer

# 设置模型缓存目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "models", "hub")
os.environ["HF_HOME"] = os.path.join(BASE_DIR, "models")
os.environ["HF_HUB_CACHE"] = MODELS_DIR
os.environ["TRANSFORMERS_CACHE"] = os.path.join(BASE_DIR, "models")
os.environ["HF_HUB_DISABLE_XET"] = "1"

# 使用国内镜像加速
if "HF_ENDPOINT" not in os.environ:
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# 配置
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
BGE_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

print("=" * 60)
print("[Embedding Service] BGE-large-zh-v1.5 嵌入服务")
print("=" * 60)

# 加载模型
print(f"\n[Model] 加载: {EMBEDDING_MODEL}")
model = None
dim = 512
try:
    model = SentenceTransformer(EMBEDDING_MODEL, local_files_only=True)
    dim = model.get_embedding_dimension()
    print(f"[Model] 完成，维度: {dim}")
except Exception as e:
    print(f"[Model] 加载失败: {e}")
    print("[Model] 尝试在线加载...")
    try:
        model = SentenceTransformer(EMBEDDING_MODEL)
        dim = model.get_embedding_dimension()
        print(f"[Model] 在线加载成功，维度: {dim}")
    except Exception as e2:
        print(f"[Model] 在线加载也失败: {e2}")
        exit(1)

print("\n" + "=" * 60)
print("嵌入服务就绪!")
print("=" * 60)

# FastAPI应用
app = FastAPI(title="Embedding Service", version="2.0.0")


class EmbedRequest(BaseModel):
    texts: List[str]
    normalize: bool = True
    model: Optional[str] = "zh"


class EmbedResponse(BaseModel):
    embeddings: List[List[float]]
    dimension: int
    model: str


@app.post("/embed", response_model=EmbedResponse)
async def embed_texts(request: EmbedRequest):
    """批量文本嵌入"""
    embeddings = model.encode(
        request.texts,
        normalize_embeddings=request.normalize,
        convert_to_numpy=True,
        show_progress_bar=False
    )
    return EmbedResponse(
        embeddings=embeddings.tolist(),
        dimension=dim,
        model=EMBEDDING_MODEL
    )


@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "models": {
            "zh": {
                "model": EMBEDDING_MODEL,
                "dimension": dim,
                "available": model is not None
            }
        }
    }


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "Embedding Service",
        "model": EMBEDDING_MODEL,
        "dimension": dim,
        "endpoints": {
            "embed": "POST /embed - 批量文本嵌入",
            "health": "GET /health - 健康检查"
        }
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8100)
