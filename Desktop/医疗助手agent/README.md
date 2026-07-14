# OpenEvidence 自进化医疗循证 Agent

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green)
![Vue](https://img.shields.io/badge/Vue-3.0+-brightgreen)
![License](https://img.shields.io/badge/License-MIT-orange)

🏥 面向临床医生的自进化医疗循证证据问答助手

[项目文档](#项目文档) • [快速开始](#快速开始) • [系统架构](#系统架构) • [API 文档](#api-文档)

</div>

---

## 📋 项目概述

**OpenEvidence** 是一个面向临床医生的自进化医疗循证证据问答助手，覆盖**高血压、高血脂、2 型糖尿病、心脑血管合并症**四大疾病领域。系统基于 RAG（检索增强生成）架构，引入 LangChain Agent 框架实现工具调用，并构建了三层自进化机制和完整的安全防护体系。

### ✨ 核心特性

| 特性 | 描述 |
|------|------|
| **🤖 Agent 工具调用** | LLM 自主决策调用 4 种工具（本地检索、外部搜索、证据评估、查询分类） |
| **🔍 混合检索架构** | BM25 + 向量检索（BGE-large-zh-v1.5, 1024维）加权融合 + CrossEncoder 重排 |
| **🌐 实时外部检索** | PubMed + EuropePMC 双源 API，当本地证据不足时自动补充最新文献 |
| **🔄 三层自进化** | 知识缺口检测与补充、策略自博弈优化、推理原则蒸馏与强化 |
| **🛡️ 安全防护体系** | 4 级风险评级、审计日志、统计显著性检验、人工审核（Human-in-the-loop） |
| **⚡ GPU 加速** | RTX 4060 支持，嵌入生成与重排序均使用 CUDA |
| **📡 SSE 流式输出** | 实时推送问答过程，提升用户体验 |

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    前端 (Vue3 + Element Plus)                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ 循证问答  │  │ 知识库管理│  │ 效果评测  │  │ 自进化监控     │   │
│  │ ChatView │  │Knowledge │  │Evaluation│  │ EvolutionView │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───────┬───────┘   │
└───────┼─────────────┼─────────────┼─────────────────┼──────────┘
        │             │             │                 │
        ▼             ▼             ▼                 ▼
┌─────────────────────────────────────────────────────────────────┐
│              后端 (FastAPI + SSE Streaming)                      │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                 Agent Loop (核心)                        │    │
│  │  工具调用 → 证据收集 → 答案生成（SSE 流式输出）         │    │
│  │  支持 ≤5 轮迭代，智能退出机制                           │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌─────────────────┐  ┌──────────────┐  ┌─────────────────┐    │
│  │  RAG 检索核心    │  │  自进化引擎   │  │  安全防护        │    │
│  │ (BM25+向量+重排)│  │  (3层进化)   │  │ (审计+审核)      │    │
│  └─────────────────┘  └──────────────┘  └─────────────────┘    │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │           SQLite 数据库 (9 张表)                         │    │
│  │   文献元数据 | 文本块 | 测试集 | 评测记录 | 经验记忆      │    │
│  │   知识缺口 | 策略优化 | 推理原则 | 审计日志              │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │        ChromaDB 向量库 (3 个 Collection)                │    │
│  │  中文指南集 | RCT元分析 | 常见研究（加权检索）          │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Agent Loop 工作流程

```
用户提问 → 领域检查 → [开始 Agent Loop]
    ↓                    ↓
不在医疗领域?         轮次1: query_classifier → 分类+疾病识别
    ↓                    ↓
  拒绝回答            轮次2: local_search → 本地知识库检索
                        ↓ (相似度<0.7? → 记录知识缺口)
                      轮次3: external_search → PubMed+EuropePMC
                        ↓ (自动保存供未来本地检索)
                      轮次4: evidence_evaluator → 评估证据充分性
                        ↓ (证据充分? → 退出循环)
                      轮次5: 生成最终答案
                        ↓
                    流式输出答案 (SSE)
```

---

## 🚀 快速开始

### 系统要求

- **操作系统**：Windows 10/11 或 Linux/macOS
- **Python**：3.10+
- **Node.js**：18+
- **CUDA**（可选）：用于 GPU 加速

### 1️⃣ 克隆项目

```bash
git clone https://github.com/spurs6/healthy_care-agent-platform.git
cd healthy_care-agent-platform
```

### 2️⃣ 环境配置

#### 安装 Python 依赖

```bash
pip install -r requirements.txt
```

**主要依赖**：
- `fastapi >= 0.109.0` - Web 框架
- `sentence-transformers >= 2.2.0` - 嵌入模型
- `chromadb >= 0.4.22` - 向量数据库
- `langchain >= 0.3.0` - Agent 框架
- `torch >= 2.0.0` - 深度学习框架

#### 创建 `.env` 配置文件

在项目根目录创建 `.env` 文件：

```env
# 硅基流动 LLM 配置
SILICONFLOW_API_KEY=your_api_key_here
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
SILICONFLOW_MODEL=Qwen/Qwen2.5-72B-Instruct

# LLM 参数
LLM_MAX_TOKENS=2048
LLM_TEMPERATURE=0.1
LLM_STREAM_TIMEOUT=60

# 嵌入模型配置
ENABLE_TRANSFORMER_EMBEDDINGS=true
ENABLE_TRANSFORMER_RERANK=false

# 服务配置
API_HOST=0.0.0.0
API_PORT=8000
API_DEBUG=false
```

#### 安装前端依赖

```bash
cd frontend
npm install --legacy-peer-deps
```

### 3️⃣ 启动服务

#### 启动后端服务

```bash
# 在项目根目录执行
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

验证后端：访问 `http://localhost:8000/` 应返回：
```json
{
  "name": "OpenEvidence 临床证据助手",
  "version": "1.0.0",
  "status": "running"
}
```

#### 启动前端服务（新终端）

```bash
cd frontend
npm run dev
```

访问前端：打开浏览器访问 `http://localhost:5173`

---

## 📁 项目结构

```
healthy_care-agent-platform/
├── README.md                          # 项目文档（本文件）
├── requirements.txt                   # Python 依赖
├── .env.example                       # 环境变量示例
├── start_all_services.py              # 一键启动脚本
│
├── backend/                           # 后端服务
│   ├── main.py                        # FastAPI 应用入口
│   ├── config.py                      # 配置管理
│   │
│   ├── agent/                         # Agent 系统
│   │   ├── agent_loop.py              # Agent 核心循环
│   │   ├── tools.py                   # 4 个工具定义
│   │   ├── external_search.py         # PubMed/EuropePMC 搜索
│   │   ├── gap_logger.py              # 知识缺口记录
│   │   ├── memory_bank.py             # 经验记忆管理
│   │   ├── reasoning_evolution.py     # 推理自进化
│   │   ├── strategy_evolution.py      # 策略自进化
│   │   └── safety_guard.py            # 安全防护系统
│   │
│   ├── rag_core/                      # RAG 检索系统
│   │   ├── bm25_retriever.py          # BM25 文本检索
│   │   ├── vector_store.py            # 向量检索（ChromaDB）
│   │   ├── query_rewriter.py          # 查询改写
│   │   └── reranker.py                # CrossEncoder 重排
│   │
│   ├── db_store/                      # 数据存储
│   │   ├── database.py                # SQLite 数据库操作
│   │   └── models.py                  # ORM 模型定义
│   │
│   ├── llm_service/                   # LLM 调用
│   │   └── llm_client.py              # 硅基流动 API 客户端
│   │
│   ├── data_collect/                  # 数据采集
│   │   ├── pubmed_api.py              # PubMed 爬虫
│   │   ├── offline_crawler.py         # 离线文献爬取
│   │   └── scheduler.py               # 定时增量更新
│   │
│   ├── doc_process/                   # 文档处理
│   │   └── pdf_parser.py              # PDF 解析
│   │
│   ├── evaluation/                    # 评测框架
│   │   └── metrics.py                 # 评测指标
│   │
│   └── routers/                       # 路由定义
│       ├── chat.py                    # 问答 API
│       ├── admin.py                   # 管理 API
│       └── eval_router.py             # 评测 API
│
├── frontend/                          # Vue3 前端
│   ├── src/
│   │   ├── App.vue                    # 根组件
│   │   ├── main.js                    # 入口文件
│   │   ├── views/
│   │   │   ├── ChatView.vue           # 循证问答页面
│   │   │   ├── KnowledgeView.vue      # 知识库管理
│   │   │   ├── EvaluationView.vue     # 效果评测
│   │   │   └── EvolutionView.vue      # 自进化监控
│   │   ├── router/
│   │   │   └── index.js               # 路由配置
│   │   ├── stores/
│   │   │   └── chat.js                # Pinia 状态管理
│   │   └── utils/
│   │       └── api.js                 # API 调用封装
│   ├── vite.config.js                 # Vite 配置
│   └── package.json                   # npm 依赖
│
├── embedding_service/                 # 独立嵌入服务
│   ├── main.py                        # 服务入口
│   └── config.py                      # 配置
│
├── scripts/                           # 工具脚本
│   ├── rebuild_vector_db.py           # 重建向量库
│   ├── init_database.py               # 初始化数据库
│   ├── eval_rag_v2.py                 # RAG 评测
│   ├── crawl_cn_literature.py         # 爬取中文文献
│   └── reparse_xml_clean.py           # XML 解析
│
├── data/                              # 数据目录（已 .gitignore）
│   ├── clinical_kb.db                 # SQLite 数据库
│   └── chroma_db/                     # ChromaDB 向量库
│
├── models/                            # 模型目录（已 .gitignore）
│   └── hub/
│       ├── models--BAAI--bge-large-zh-v1.5/
│       └── models--BAAI--bge-small-zh-v1.5/
│
├── experiments/                       # 实验结果
│   └── *.json                         # 评测日志
│
├── test_set/                          # 测试集
│   └── clinical_evidence_test_v3.json # 测试样例
│
└── docs/                              # 文档
    └── evaluation_guide.md            # 评测指南
```

---

## 📡 API 文档

### 基础端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 服务信息 |
| `/health` | GET | 健康检查 |

### 聊天 API

#### 问答（非流式）
```http
POST /api/chat/query
Content-Type: application/json

{
  "query": "高血压患者的首选降压药物是什么？",
  "user_id": "user123",
  "conversation_id": "conv456"
}
```

**响应示例**：
```json
{
  "status": "success",
  "answer": "根据最新的循证医学证据...",
  "references": [
    {
      "id": "PMC123456",
      "title": "...",
      "authors": "...",
      "year": 2024
    }
  ],
  "confidence": 0.95
}
```

#### 问答（流式 SSE）
```http
POST /api/chat/stream
Content-Type: application/json

{
  "query": "高血压患者的首选降压药物是什么？",
  "user_id": "user123"
}
```

**SSE 响应流**：
```
data: {"type": "thinking", "content": "正在分类查询..."}
data: {"type": "searching", "content": "正在搜索本地知识库..."}
data: {"type": "chunk", "content": "根据最新的循证医学证据..."}
data: {"type": "done", "references": [...]}
```

### 管理 API

#### 知识库统计
```http
GET /api/admin/stats
```

#### 文档列表
```http
GET /api/admin/documents?skip=0&limit=10
```

### 评测 API

#### 运行评测
```http
POST /api/eval/run
Content-Type: application/json

{
  "test_file": "test_set/clinical_evidence_test_v3.json",
  "num_samples": 10
}
```

---

## 🔧 开发指南

### 向量库重建

当修改嵌入模型或新增文献后，需重建向量库：

```bash
python scripts/rebuild_vector_db.py
```

### 数据库初始化

```bash
python scripts/init_database.py
```

### 本地调试

使用 API 测试工具（如 Postman 或 curl）测试后端接口：

```bash
# 测试健康状态
curl http://localhost:8000/health

# 测试问答 API
curl -X POST http://localhost:8000/api/chat/query \
  -H "Content-Type: application/json" \
  -d '{"query": "高血压怎么治疗？"}'
```

### 日志和调试

启用调试模式（在 `.env` 中设置）：
```env
API_DEBUG=true
```

查看应用日志：
```bash
# 后端日志会在控制台输出
# 前端日志可在浏览器开发者工具中查看
```

---

## ⚡ 性能优化建议

### 1. GPU 加速

确保 CUDA 安装正确：
```bash
python -c "import torch; print(torch.cuda.is_available())"
```

### 2. 向量库优化

- 定期重建向量库以保持索引效率
- 调整 ChromaDB 的 `search_type` 参数

### 3. LLM 调用优化

- 使用流式输出减少端到端延迟
- 配置合适的 `max_tokens` 避免超时

---

## ❓ 常见问题 (FAQ)

### Q: 后端启动报 `ModuleNotFoundError`
**A**: 执行 `pip install -r requirements.txt` 重新安装所有依赖，或单独安装缺失模块。

### Q: 前端页面空白
**A**: 检查 `frontend/vite.config.js` 中的代理配置，确保指向 `http://localhost:8000`。

### Q: LLM 问答返回 429 错误
**A**: 这是硅基流动 API 速率限制。可以：
- 增加 API 配额
- 更换模型（如 `Qwen/Qwen2.5-7B-Instruct`）
- 稍后重试

### Q: 嵌入模型加载失败
**A**: 确保 `models/hub/` 下有完整的模型权重文件（检查文件大小，避免 0 字节文件）。

### Q: 向量检索结果不理想
**A**: 尝试以下方案：
- 重建向量库：`python scripts/rebuild_vector_db.py`
- 调整 BM25 和向量检索的权重组合
- 使用不同的重排模型

### Q: 如何添加新的文献？
**A**: 
1. 将文献放入数据目录
2. 运行 `python scripts/crawl_cn_literature.py` 爬取或手动导入
3. 执行 `python scripts/rebuild_vector_db.py` 重建向量库

---

## 📊 数据库表结构

### SQLite 数据库（`data/clinical_kb.db`）

| 表名 | 说明 |
|------|------|
| `table_article_meta` | 文献元数据（标题、作者、年份、全文） |
| `table_chunk` | 文献分块文本 |
| `table_test_set` | 测试集样例 |
| `table_eval_record` | 评测记录 |
| `table_memory_bank` | 经验记忆库 |
| `table_knowledge_gap` | 知识缺口日志 |
| `table_strategy_opt` | 策略优化记录 |
| `table_reasoning_rule` | 推理原则库 |
| `table_audit_log` | 系统审计日志 |

### ChromaDB 向量库（`data/chroma_db/`）

| Collection | 权重 | 说明 |
|----------|------|------|
| `coll_cn_guide` | 1.5 | 中文诊疗指南 |
| `coll_rct_meta` | 1.0 | RCT 和元分析 |
| `coll_common_study` | 0.5 | 其他常见研究 |

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

### 提交流程

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

---

## 📄 许可证

本项目采用 [MIT License](LICENSE) 许可证。

---

## 👥 作者

- **项目名**：OpenEvidence 自进化医疗循证 Agent
- **开发者**：Health Care Agent Platform Team
- **最后更新**：2026 年 7 月

---

## 📞 联系与支持

- 📧 Email：support@example.com
- 🐛 Bug 反馈：[GitHub Issues](https://github.com/spurs6/healthy_care-agent-platform/issues)
- 💡 功能建议：[GitHub Discussions](https://github.com/spurs6/healthy_care-agent-platform/discussions)

---

## 🙏 致谢

感谢以下开源项目的支持：
- [FastAPI](https://fastapi.tiangolo.com/)
- [LangChain](https://langchain.com/)
- [Sentence Transformers](https://www.sbert.net/)
- [ChromaDB](https://www.trychroma.com/)
- [Vue.js](https://vuejs.org/)

---

<div align="center">

**⭐ 如果本项目对你有帮助，请给个 Star！**

Made with ❤️ by the OpenEvidence Team

</div>
