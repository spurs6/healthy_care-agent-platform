"""
本地嵌入服务配置
"""
LOCAL_EMBEDDING_URL = os.getenv("LOCAL_EMBEDDING_URL", "http://localhost:8100")
USE_LOCAL_EMBEDDING = os.getenv("USE_LOCAL_EMBEDDING", "true").lower() == "true"