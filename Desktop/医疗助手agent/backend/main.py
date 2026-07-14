"""
OpenEvidence 临床证据助手 - FastAPI主入口
"""
import os
import sys
from pathlib import Path

# 禁用 HuggingFace Hub 在线检查，避免背景线程 SSL 错误
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from contextlib import asynccontextmanager
import asyncio

from backend.config import API_HOST, API_PORT, CORS_ORIGINS, get_config_summary
from backend.db_store import db_manager
from backend.rag_core import embedding_model, rerank_model
from backend.data_collect import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    print("\n[OpenEvidence] 临床证据助手启动中...")
    
    # 初始化数据库
    db_manager.init_database()
    
    # 预加载嵌入模型（可选，首次使用时加载）
    print("[OpenEvidence] 嵌入模型将在首次检索时加载...")
    
    # 启动定时任务调度器
    scheduler.start()
    
    print(f"[OpenEvidence] 服务已启动: http://{API_HOST}:{API_PORT}")
    print(f"[OpenEvidence] 配置: {get_config_summary()}")
    
    yield
    
    # 关闭时清理
    scheduler.stop()
    print("[OpenEvidence] 服务已停止")


# 创建FastAPI应用
app = FastAPI(
    title="OpenEvidence 临床证据助手",
    description="面向临床医生的心脑血管、高血压、高血脂、糖尿病循证证据问答助手",
    version="1.0.0",
    lifespan=lifespan
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== API路由 ====================
from backend.routers import chat, admin, eval_router

app.include_router(chat.router, prefix="/api/chat", tags=["问答"])
app.include_router(admin.router, prefix="/api/admin", tags=["知识库管理"])
app.include_router(eval_router.router, prefix="/api/eval", tags=["自动化评测"])


# ==================== 全局异常处理 ====================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "message": "服务器内部错误"}
    )


# ==================== 基础接口 ====================
@app.get("/")
async def root():
    """服务根路径"""
    return {
        "name": "OpenEvidence 临床证据助手",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


@app.get("/config")
async def get_config():
    """获取当前配置"""
    return get_config_summary()


# ==================== 启动命令 ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=True
    )