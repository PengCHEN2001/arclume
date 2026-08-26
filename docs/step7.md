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

## 本阶段实际采用的 RAG 策略

本阶段的目标是先把“文档 → 检索 → Context → 模型”整条链路打通，因此先
采用简单、可观察、容易替换的基线策略，不把查询改写、重排和复杂评测提前
加入。

### 1. 检索触发策略

当前每条聊天消息都会尝试查询知识库：

```text
用户消息
  → KnowledgeBase.search_async()
  → 返回最多 3 个结果
  → 放入 Context
```

当前还没有意图识别，所以问候、感谢和闲聊也会触发检索。后面加入
`IntentRecognizer` 后，会改成：

```text
业务问题，例如退款、物流、账户、技术问题 → 查询 RAG
问候、闲聊、明确转人工等请求             → 不查询 RAG
```

### 2. 文档切片策略

当前目标片段长度是约 500 个字符，具体方式是：

```text
1. 合并多余空白
2. 尽量在句号、问号、感叹号等句子边界切分
3. 当前片段超过目标长度时，开始新的片段
4. 单个句子本身过长时，再按长度硬切
```

当前不使用 `chunk overlap`。这样实现简单，但可能丢失两个片段边界之间的
少量语义联系，后续需要通过评测决定是否增加重叠区域。

### 3. Embedding 策略

当前代码没有单独实现 Embedding 服务，也没有指定自己的 Embedding 模型。写
入和查询时把文本交给 ChromaDB，由 ChromaDB 的默认 Embedding 机制生成向量：

```text
add/upsert 文本 → ChromaDB 生成文档向量
query_texts     → ChromaDB 生成查询向量
```

这个选择是为了先减少配置和代码量。具体默认模型、模型下载方式和服务端行
为，需要在实际安装并启动 ChromaDB 后验证；当前本地还没有进行真实向量检索
测试。

后续会明确固定 Embedding 模型和版本，并保证文档入库与查询使用同一个模型。
如果更换 Embedding 模型，需要重新生成并导入全部文档向量。

### 4. 召回数量和相似度策略

当前 Agent 使用：

```text
knowledge_top_k = 3
```

知识库测试接口默认使用 `top_k=5`。`KnowledgeBase` 会把请求数量限制在
1 到 20 之间，避免一次请求召回过多内容。

当前会把 ChromaDB 返回的距离简单转换成：

```text
score = 1 - distance
```

并限制在 0 到 1 之间。当前没有设置最低相似度阈值，因此即使结果相关性较
低，也可能进入 Context。后续会通过评测决定是否增加 threshold，以及是否
需要保留原始距离而不是直接转换成通用分数。

### 5. 查询策略

当前直接使用用户原始问题作为 query：

```text
用户原话 → ChromaDB query_texts
```

当前不做：

```text
查询改写
多角度子查询
同义词扩展
关键词检索和向量检索融合
LLM 重排
```

先使用原始问题，是为了确认最基础的语义检索是否有效。后面如果发现用户
问题口语化、信息不完整或一个问题包含多个意图，再考虑增加查询改写和多路
召回。

### 6. Metadata 和权限策略

当前每个片段保存：

```text
title
source
chunk_index
total_chunks
```

当前只保存这些字段用于展示和排查，不根据部门、地区、产品、语言、租户或
权限做过滤。当前演示知识库也没有敏感信息。

后续面向真实企业数据时，需要增加文档版本、业务领域、适用地区、语言、租
户和访问权限等字段，并在检索前进行过滤，避免把不属于当前用户或客服权限
范围的内容传给模型。

### 7. 文档导入和更新策略

当前知识库为空时，自动导入 `data/demo_docs/` 中的演示文档。文档切片后使
用稳定的 SHA-256 作为片段 ID，并使用 `upsert()`：

```text
同一份文档重复导入 → 更新原片段，不持续制造重复数据
```

当前没有文档删除、版本回滚、增量识别和后台上传功能。后续知识库管理能力
稳定后，再补充文档版本和重新索引流程。

### 8. Context 注入策略

当前检索结果以一个结构化的 system message 放进 Context：

```text
[Relevant knowledge]
检索结果 JSON
```

模型最终看到的顺序是：

```text
system prompt
  → AgentState
  → Relevant knowledge
  → 历史对话
  → 当前用户问题
```

当前没有强制模型输出来源引用，也没有在模型回答后再次验证回答是否严格依
据知识库。后续可以根据客服场景要求增加来源标识、回答依据检查和拒答规则。

### 9. 检索失败策略

如果 ChromaDB 没有安装、服务不可用或查询失败：

```text
记录 warning
→ knowledge_results 置为空
→ 继续使用 Memory、State 和基础客服逻辑回答
```

这样可以避免知识库服务的短暂故障直接阻塞整个客服接口。后续可以根据业务
风险决定某些高风险问题是否必须要求 RAG 成功，否则转人工，而不是所有问题
都采用同一个降级策略。

## 当前策略的定位

以上策略只是第七步的可运行基线，不代表最终 RAG 方案。当前最重要的是确认：

```text
文档能否正确切片
文档能否写入 ChromaDB
查询能否召回相关片段
结果能否进入 Context
知识库故障时主链路能否继续
```

后续会在加入意图识别、真实业务 Tool 和评测体系后逐步完善：

```text
第十步附近：按意图决定是否触发 RAG
第十一步：评测 chunk、Embedding、Top-K、threshold 和召回质量
后续：查询改写、多路召回、混合检索、rerank、权限过滤和文档版本管理
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
