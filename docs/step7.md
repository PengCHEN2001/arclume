# 第七步：加入知识库检索（RAG）

## 当前项目目录

```text
arclume/
├── api/
│   ├── __init__.py                 # Python 包声明
│   └── main.py                    # FastAPI 入口、聊天接口和知识库测试接口
├── agents/
│   ├── __init__.py                 # Python 包声明
│   └── customer_service_agent.py  # 单 Agent 客服逻辑
├── core/
│   ├── __init__.py                 # Python 包声明
│   ├── llm_utils.py               # 大模型 HTTP 调用
│   └── context_builder.py         # 组装一次模型请求的 Context
├── harness/
│   ├── __init__.py                 # Python 包声明
│   ├── policy.py                  # Tool 权限和风险判断
│   ├── executor.py                # Tool 执行和结果统一
│   ├── trace.py                   # Harness 事件记录
│   └── runtime.py                 # Harness 运行控制和最小循环
├── knowledge/
│   ├── __init__.py                # KnowledgeBase 异常类型
│   └── knowledge_base.py          # ChromaDB 文档入库和语义检索
├── memory/
│   ├── __init__.py                 # MemoryStoreError
│   ├── conversation_memory.py     # Redis 短期对话记忆
│   └── state_store.py             # Redis AgentState 保存
├── schemas/
│   ├── __init__.py                 # Python 包声明
│   ├── api.py                     # API 请求和响应模型
│   ├── state.py                   # AgentState 模型
│   ├── context.py                 # Context 模型
│   └── tool.py                    # ToolCall 和 ToolResult 模型
├── data/
│   └── demo_docs/                 # 本地演示知识文档
│       ├── account_security.md    # 账户安全规则
│       ├── refund_policy.md       # 退款规则
│       ├── shipping_policy.md     # 配送规则
│       └── technical_support.md   # 技术排障规则
├── docs/
│   ├── step1.md                  # 第一步记录
│   ├── step2.md                  # 第二步记录
│   ├── step3.md                  # 第三步记录
│   ├── step4.md                  # 第四步记录
│   ├── step5.md                  # 第五步记录
│   ├── step6.md                  # 第六步记录
│   └── step7.md                  # 第七步记录
├── .env.example                  # 环境变量模板
├── .gitignore                    # Git 忽略规则
├── .dockerignore                 # Docker 构建忽略规则
├── Dockerfile                    # 应用镜像描述，暂不测试
├── docker-compose.yml             # API、Redis 和 ChromaDB 服务编排
├── requirements.txt              # Python 依赖
└── README.md                     # 项目说明
```

## 本步目标

前面 ContextBuilder 已经可以接收 `knowledge_results`，但实际还没有任何
模块去产生这些结果。本步补上最小的 RAG 链路：

```text
知识文档
  → 切成文档片段
  → 写入 ChromaDB knowledge_base collection
  → 根据用户问题做语义检索
  → 检索结果放入 Context
  → 模型参考相关知识回答
```

本步只做单次查询和基础文档入库，不做以下内容：

```text
- 意图识别后再决定是否检索
- 查询改写和多查询召回
- LLM 重排
- 长期情景记忆和用户画像
- 真实订单、退款或物流 Tool
- 多 Agent 路由
```

这些内容分别留到后续步骤。当前所有代码注释和非 `docs/` 文档使用英文；本
步骤说明文件使用中文。

## 为什么使用 ChromaDB

客服规则、退款说明、配送说明等内容不应该硬编码在客服 Agent 的对话历史
里。把它们独立保存为知识文档后，系统可以：

```text
文档更新 → 重新入库 → 后续问题使用新内容
```

ChromaDB 负责保存文档片段和向量检索，`ContextBuilder` 只负责接收检索
结果并把它放入本次模型请求。两者职责分开：

```text
KnowledgeBase：文档管理和检索
ContextBuilder：本次请求的上下文排列
LLMClient：向模型发送最终消息
```

本项目当前优先使用独立的 ChromaDB 服务。这样开发环境和后续部署环境使用
同一个知识库位置，不会因为本机是否安装服务而悄悄产生两份数据。只有显式
设置 `CHROMA_ALLOW_LOCAL_FALLBACK=true` 时，才允许退回本地持久化模式。

## 本步新增和修改的文件

```text
knowledge/__init__.py                # 新增：知识库异常类型
knowledge/knowledge_base.py          # 新增：文档入库、切片和语义检索
data/demo_docs/*.md                  # 新增：客服演示知识文档
agents/customer_service_agent.py     # 修改：在构建 Context 前查询知识库
api/main.py                           # 修改：创建知识库并增加检索测试接口
requirements.txt                     # 修改：加入 chromadb 客户端
.env.example                          # 修改：加入 ChromaDB 配置字段
Dockerfile                            # 修改：复制 knowledge 和 data 目录
docker-compose.yml                    # 修改：明确 Redis 和 ChromaDB 当前用途
README.md                             # 修改：更新第七步状态
docs/step7.md                         # 新增：本步骤设计和测试记录
```

## 一次 `/chat` 请求的运行流程

```text
服务启动
  → 创建 LLMClient
  → 创建 Redis ConversationMemory 和 StateStore
  → 创建 KnowledgeBase
  → 尝试连接 ChromaDB
  → knowledge_base collection 为空时导入 data/demo_docs
```

一次聊天请求：

```text
1. API 接收 ChatRequest
2. Agent 从 Redis 读取历史消息和 AgentState
3. Agent 保存当前用户消息
4. KnowledgeBase.search_async() 查询相关文档片段
5. ContextBuilder.build() 把结果写入 Context.knowledge_results
6. ContextBuilder.render_history() 把知识结果渲染成模型可读消息
7. LLMClient 把 system prompt、知识结果、历史消息和当前问题发送给模型
8. Agent 保存模型回复和更新后的 AgentState
9. API 返回 ChatResponse
```

实际调用关系：

```text
api/main.py
  → agents/customer_service_agent.py
      ├─ memory/conversation_memory.py
      ├─ memory/state_store.py
      ├─ knowledge/knowledge_base.py
      │    └─ ChromaDB
      ├─ core/context_builder.py
      │    └─ schemas/context.py
      └─ core/llm_utils.py
           └─ 外部模型服务
```

如果 ChromaDB 暂时不可用：

```text
KnowledgeBase.search_async()
  → 抛出知识库异常
  → Agent 记录 warning
  → knowledge_results 为空
  → 继续使用原有对话和 State 完成回答
```

也就是说，RAG 是增强信息来源，当前不会让整个客服主链路因为检索服务暂
时不可用而停止。

## `knowledge/knowledge_base.py`

### 文件作用

负责把文本文档切成片段、写入 ChromaDB，并根据用户问题返回相似片段。它不
负责调用大模型、不负责生成回复，也不负责决定 Agent 是否应该检索。

### 类：`KnowledgeBase`

核心属性：

```text
chroma_host：ChromaDB 服务地址
chroma_port：ChromaDB 服务端口
local_path：可选的本地持久化路径
allow_local_fallback：是否允许服务不可用时使用本地模式
chunk_size：文档片段的目标字符数
_client：ChromaDB 客户端，第一次使用时创建
_collection：knowledge_base collection，第一次使用时打开
_mode：当前使用 server、local 或 injected 模式
```

核心方法：

```text
from_environment()：从 CHROMA_* 环境变量创建 KnowledgeBase
initialize_async()：连接服务并在空库时导入演示文档
add_documents()：切片并幂等写入文档
add_directory()：读取目录中的 md/txt/json 文件并写入
search()：同步语义检索
search_async()：在线程池中执行同步检索
doc_count：返回当前文档片段数
close()：应用关闭时释放资源
_ensure_collection()：延迟创建客户端和 collection
_chunk_text()：按句子边界和长度切分文本
_chunk_id()：为片段生成稳定 ID
_read_document()：读取普通文本或 JSON 文件
```

依赖：`chromadb`、Python 标准库。

被谁调用：

```text
api/main.py：创建和初始化 KnowledgeBase
agents/customer_service_agent.py：执行聊天前的语义检索
```

### 文档片段字段

每个片段在 ChromaDB 中保存：

```text
id：由 source、chunk_index 和内容计算出的稳定 SHA-256
document：实际的文本片段
title：文档标题
source：文档来源路径或来源标识
chunk_index：片段在原文中的序号
total_chunks：原文被切成的片段总数
```

使用 `upsert()` 而不是只使用 `add()`，是为了让同一份文档重复索引时不会
不断产生重复片段。

### 检索结果格式

`search()` 返回的每个结果大致是：

```json
{
  "title": "Refund Policy",
  "source": "data/demo_docs/refund_policy.md",
  "content": "Customers can request...",
  "score": 0.82,
  "chunk": 0
}
```

这些字典会直接放进 `Context.knowledge_results`，然后由
`ContextBuilder` 序列化为模型可以阅读的内容。

## `agents/customer_service_agent.py` 的变化

新增属性：

```text
knowledge_base：可选的 KnowledgeBase
knowledge_top_k：每次最多检索的片段数，当前默认 3
```

`respond()` 现在的主要顺序：

```text
读取 Memory 和 State
  → 保存当前用户消息
  → 查询 KnowledgeBase
  → 构建 Context
  → 调用 LLMClient
  → 保存客服回复和更新 State
```

当前 Agent 会对每条消息尝试检索。这是为了先打通数据链路；等第十步加入
IntentRecognizer 后，再改成只有退款、物流、账户等业务意图才检索，问候和
闲聊不浪费检索成本。

## `api/main.py` 新增接口

### `GET /knowledge/search`

用途：不调用大模型，直接检查知识库检索是否工作。

示例：

```bash
curl --get 'http://127.0.0.1:8000/knowledge/search' \
  --data-urlencode 'query=How long does a refund take?' \
  --data-urlencode 'top_k=3'
```

### `GET /knowledge/stats`

用途：查看 `knowledge_base` collection 当前有多少个文档片段。

```bash
curl http://127.0.0.1:8000/knowledge/stats
```

这两个接口只是本阶段的验证入口。未来如果需要知识库管理后台，再增加鉴
权后的文档上传、删除、版本管理和重新索引接口。

## 配置

`.env.example` 新增：

```text
CHROMA_HOST=localhost
CHROMA_PORT=8001
CHROMA_PERSIST_DIRECTORY=./data/chroma
CHROMA_ALLOW_LOCAL_FALLBACK=false
CHROMA_CHUNK_SIZE=500
```

本机连接独立服务时使用 `localhost:8001`；Docker Compose 中，API 容器使用
`chromadb:8000`。Docker 文件本步只更新配置，不进行本机 Docker 测试。

## 本步测试方式

不需要调用真实模型 API。需要实际检索时，先保证 Redis 和 ChromaDB 服务可
用，再启动 API：

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

另开终端检查：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/knowledge/stats
curl --get 'http://127.0.0.1:8000/knowledge/search' \
  --data-urlencode 'query=What is the refund policy?'
```

如果 ChromaDB 没启动，`/knowledge/search` 会返回 `503`，但 `/health` 仍然
可以查看 API 状态，客服 Agent 也会跳过知识结果继续运行。当前不执行需要真
实模型 API Key 的 `/chat` 测试。

## 本步完成标准

```text
完成：KnowledgeBase 可以切片、入库和检索文档
完成：检索结果可以进入 ContextBuilder
完成：Agent 可以在检索失败时继续工作
完成：提供无模型调用的知识库测试接口
完成：ChromaDB 配置、依赖和 Docker 文件保持一致
暂不完成：意图路由、查询改写、重排、长期记忆和真实业务 Tool
```
