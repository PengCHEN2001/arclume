# Arclume：让客服请求先被理解、取证，再得到回答

Arclume 是一个面向**英文客服对话**的多 Agent 后端原型。真实用户往往不会按系统预设的分类提问：一句话可能同时说“登录不了”和“被重复扣费”，下一句又只说“那这个怎么办”。项目要处理的不只是生成一段通顺的文字，还包括判断有哪些问题、分别由谁处理、回答前缺少什么证据，以及哪些操作不能擅自执行。

它把这些判断放在可观察的工程链路中：**理解请求 → 制定处理计划 → 按需取证 → Agent 协作 → 生成回复 → 保存与追踪**。大模型负责生成和必要时的复核，但不独自决定整个流程。

> Arclume 是一个个人学习与工程实践项目。 当前版本刻意不依赖 LangChain、LangGraph 等高层 Agent 框架。它们能加快原型开发，但会隐藏状态传递、编排、工具调用与错误处理等核心机制，不利于理解和验证系统本身的设计。
>
> 因此，Arclume 先用 Python 显式实现意图识别、路由、Context 组装、Tool Call Loop、Memory 与 Trace。后续会补充 LangChain / LangGraph 对照版本，比较框架方案与当前方案在开发效率、可观测性、调试体验和维护成本上的差异。
>
> 实现阶段使用了 AI coding 协助代码编写、重构和测试；项目的架构、模块划分、核心处理链路与验证方案由作者持续设计和调整。当前仍有部分实现细节在验证和迭代中。


[English README](../../README.md)

## 项目结构

```text
arclume/
├── api/          FastAPI 接口、应用启动与共享组件装配
├── agents/       Agent 路由、角色定义、执行和回答合并
├── core/         意图识别、模型客户端、Skill 与 Context 组装
├── memory/       Redis 会话记忆、ChromaDB 长期记忆和处理状态
├── knowledge/    文档切片、向量检索与 BM25 检索
├── tools/        知识检索、订单/物流等具体工具能力
├── harness/      工具权限、参数校验、风险判断、执行与 Trace
├── frontend/     可选的 Vue/Vite Web 对话界面
├── data/         演示知识文档和本地生成的数据目录
├── docs/         学习、设计、代码和评测文档
├── evaluation/   离线评测用例、指标和报告逻辑
├── tests/        不依赖真实外部服务的回归测试
├── config/       Prometheus、Nginx 等运行配置
├── README.md     面向项目使用者的英文入口文档
├── requirements.txt Python 后端依赖清单
├── docker-compose.yml API、Redis、ChromaDB、Prometheus 的本地容器编排
├── Dockerfile    后端 API 镜像构建说明
├── .gitignore    Git 不应提交的本地文件规则
└── .dockerignore Docker 构建时应排除的文件规则
```

## 其他说明类文档
- [产品需求文档（PRD）](PRD_zh.md)：目标用户、问题定义、首版范围、关键需求、验收标准与待验证假设。
- [项目设计与全链路](项目设计与全链路.md)：请求链路、各层设计与取舍。
- [代码结构与实现指南](code_guide_zh.md)：目录、主要文件、类与函数、配置和修改入口。
- [评测体系与运行方法](evaluation_protocol_zh.md)：数据集、指标、运行命令和结果边界。
- [路线图](roadmap_zh.md)：公开展示前的验证清单和后续迭代方向。


## 它能处理什么样的复杂消息？

例如，用户发送：

> I cannot log in and I was charged twice.

这不是一个简单的“登录问题”或“账单问题”。Arclume 会从两个独立的问题片段中提取证据，选择主 Agent 和辅助 Agent，让 Technical 与 Billing 分别处理自己的部分，并行执行后合并成一条给用户的回复。下一轮会话读取的是**合并后的最终回答**，而不只是某个 Agent 的草稿。

同样，如果一条消息同时询问物流时效、Mini 台灯介绍和退款流程，系统会把“物流 + 产品介绍”交给 General Agent，把“退款”交给 Billing Agent。每个 Agent 只使用自己的子问题做检索和回答，避免两个 Agent 都拿到完整消息后重复回答三遍。

其他分支也有明确用途：问退款政策时，先尝试检索知识库；提供订单号查询状态时，才考虑相应的只读业务工具；“那个问题怎么办”一类无法可靠判断的消息，可以结合历史或先要求澄清；明确要求人工时，进入确定性的升级提示路径。**这些能力表示系统有处理复杂请求的机制，不表示它已能核实真实支付记录或接通人工坐席。**


## 和单轮客服问答原型有什么不同？

这里对比的是“把整句话交给一个 Prompt 直接回答”的简单原型，不是说所有客服系统都没有这些能力。

| 关注点 | Arclume 的做法 |
| --- | --- |
| 一句话里有多个问题 | 识别消息中的独立领域并生成领域子任务；主 Agent 与辅助 Agent 只处理分配给自己的子问题，再合并为一条回复。 |
| 回答需要依据 | 系统会判断当前问题是否需要查询知识库：退款政策、商品保修、登录故障等通常会触发检索，普通聊天则跳过。检索得到的相关知识片段会被加入 Agent 上下文，帮助模型基于资料回答，而不是只依赖模型自身记忆。 |
| 用户继续追问 | Redis 保存近期消息、摘要和处理状态；ChromaDB 可召回历史摘要和用户画像；最终回复会写回会话，供下一轮继续参考。 |
| 模型想调用工具 | AgentProfile 限定每个 Agent 的职责和可用工具；所有工具调用还要经过 Arclume 内部的 Harness。Harness 负责校验工具权限、参数和风险边界，执行调用并记录 Trace，高风险操作不会由模型直接执行。 |
| 回答出了问题 | `request_id` 可关联意图、路由、检索和工具 Trace；离线评测可分别检查意图、路由、检索，而不只看最终文字。 |

这条链路的几个设计亮点是：**意图与证据需求分开**，让“退款政策”去找知识、“订单当前状态”考虑实时数据；**RAG 使用 Dense + BM25 混合召回**，兼顾语义近似与错误码、订单号等精确词，再经融合、去重和排序筛选片段；**角色、Skill 与工具治理分层**，使提示词、业务规范和执行权限可以独立调整。默认采用本地规则完成意图判断、查询改写和 RAG 排序；疑难意图复核、LLM 辅助改写及 LLM 重排是可选项，不必为每次请求都增加模型调用。

这仍是一个可扩展的工程原型：复杂请求的识别依赖现有规则、模板和可选模型复核，并不保证所有表达都能正确拆分。检索到资料也不等于最终答案一定正确，效果需要用真实英文客服数据继续评估。

一次请求只会走它需要的分支：

```text
POST /chat
  → 读取会话记忆
  → 识别意图和所需证据
  → 路由到单 Agent、多 Agent、澄清或人工升级
  → 按需检索知识或调用允许的工具
  → 生成并合并回复
  → 保存用户实际看到的最终对话，再返回响应
```

主链路代码分布在 `api/`、`core/`、`agents/`、`memory/`、`knowledge/`、`tools/` 和 `harness/`。服务运行后可在 `/docs` 查看交互式接口文档。

## 快速运行

Arclume 运行时需要 Chat 模型接口、Redis、ChromaDB 和 Arclume API；Web 前端可以按需启动。开始前先选择一种运行方式：

| 运行方式 | Arclume API | Redis | ChromaDB | 适用场景 |
| --- | --- | --- | --- | --- |
| Docker Compose | Docker 容器 | Docker 容器 | Docker 容器 | 最快体验完整项目，推荐首次使用 |
| 完全不使用 Docker | 本机 Python 环境 | 本机 `redis-server` | Python 本地持久化模式 | 本地开发和阅读代码 |
| 使用已有服务 | 本机 Python 环境 | 已有本地或远程服务 | 已有本地或远程服务 | 已经具备基础设施的环境 |

无论选择哪种方式，整体过程都是：

```text
准备模型与存储配置
→ 准备 Redis 和 ChromaDB
→ 启动 Arclume API
→ 空知识库自动导入 data/demo_docs/
→ 检查后端与 RAG
→ 启动 Web 前端并开始对话
```

Redis、ChromaDB 和知识索引都运行在使用者自己的电脑或自己配置的服务中，不会连接项目作者电脑上的数据库。

### 配置模型接口

所有运行方式都需要在仓库根目录创建 `.env`，配置一个兼容 OpenAI Chat Completions 协议的模型接口。`.env` 属于本地运行密钥文件，不建议提交到 GitHub；即使删掉个人值也不推荐上传。公开仓库里只保留 `.env.example` 这类占位模板，用来说明需要哪些变量。

第一次运行时，先复制模板，再修改复制出来的 `.env`，不要直接把真实密钥写进 `.env.example`：

```bash
cp .env.example .env
```

至少需要检查下面这些值：

```dotenv
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-chat-model
REDIS_PASSWORD=arclume123
ARCLUME_INTENT_LLM_ENABLED=false
ARCLUME_RAG_LLM_ENABLED=false
ARCLUME_MEMORY_LLM_ENABLED=false
```

这三个可选开关关闭后，意图复核、RAG 查询改写与重排、记忆处理不会额外调用模型；**普通 Agent 生成回复仍然会调用 Chat 模型**。若只调用知识检索接口，可以暂不配置可用的 Chat 模型。`REDIS_PASSWORD` 仅供 Docker Compose 的本地 Redis 使用。

### 方式一：使用 Docker Compose

完成前面的 `.env` 配置后，如果选择 Docker 运行，需要先安装并启动 Docker Desktop。

在仓库根目录执行：

```bash
docker compose up -d --build api
docker compose ps
```

第一条命令会构建并启动 Arclume API。由于 API 依赖 Redis 和 ChromaDB，Docker Compose 会自动完成以下操作：

```text
启动 Redis
→ 启动 ChromaDB
→ 等待 Redis 和 ChromaDB 可用
→ 启动 Arclume API
```

第二条命令用于查看服务状态。正常情况下，应当能看到 `api`、`redis` 和 `chromadb` 正在运行。

如果 API 启动失败，可以查看日志：

```bash
docker compose logs api
```

持续观察日志可以使用：

```bash
docker compose logs -f api
```

### 方式二：完全不使用 Docker

不使用 Docker 时，需要在本机运行 Redis。ChromaDB 不需要单独启动，Arclume 会使用安装在 Python 环境中的本地 ChromaDB，并将数据保存在 `data/chroma/`。

#### 1. 安装 Python 依赖并补充配置

在仓库根目录创建并激活 Python 3.10 虚拟环境：

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

在前面创建的 `.env` 中加入：

```dotenv
REDIS_URL=redis://:arclume123@127.0.0.1:6379/0
CHROMA_HOST=127.0.0.1
CHROMA_PORT=8001
CHROMA_ALLOW_LOCAL_FALLBACK=true
CHROMA_PERSIST_DIRECTORY=./data/chroma
```

#### 2. 安装并启动 Redis

如果本机尚未安装 Redis，macOS 可以使用 Homebrew 安装：

```bash
brew install redis
```

在终端 A 中启动 Redis： 这里的密码必须与 `.env` 中 `REDIS_URL` 的密码一致。

```bash
redis-server \
  --port 6379 \
  --requirepass arclume123 \
  --save '' \
  --appendonly no
```


可以在另一个终端检查 Redis：

```bash
redis-cli -a arclume123 ping
```

返回下面内容表示 Redis 已启动：

```text
PONG
```

这个启动方式不会将 Redis 数据持久化到磁盘，适合本地开发和项目体验。关闭运行 Redis 的终端后，会话数据也会丢失。

#### 3. 启动 Arclume API

在终端 B 中进入项目根目录，激活虚拟环境：

```bash
cd /path/to/arclume
source .venv/bin/activate
```

然后启动 API：

```bash
python -m uvicorn api.main:app \
  --host 127.0.0.1 \
  --port 8000
```

API 会先尝试连接 `.env` 中配置的 ChromaDB 服务。如果没有可用的 ChromaDB 服务，就会自动回退到本地模式，并在下面的目录保存知识库：

```text
data/chroma/
```

API 启动后，继续按照下面的“检查服务与知识库”“启动 Web 界面”和“通过 API 对话”步骤操作。

### 方式三：使用已有的 Redis 或 ChromaDB 服务

如果已经有可用的本地或远程服务，先按照方式二安装 Python 依赖，再在 `.env` 中填写实际连接地址：

```dotenv
REDIS_URL=redis://username:password@redis-host:6379/0
CHROMA_HOST=chroma-host
CHROMA_PORT=8000
CHROMA_ALLOW_LOCAL_FALLBACK=false
```

然后从仓库根目录启动 API：

```bash
source .venv/bin/activate
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

这条方式不会自动启动 Redis 或 ChromaDB，它只连接 `.env` 指定的服务。远程服务的认证、网络访问、持久化和数据权限由实际运行环境负责。当前 `docker-compose.yml` 默认使用 Compose 内部服务；连接已有服务时，直接从本机 Python 环境启动 API 更简单。

### 首次启动时如何建立知识库

三种方式使用相同的入库流程。只要当前 ChromaDB 的 `knowledge_base` 集合为空，Arclume API 启动时就会自动执行：

```text
读取 data/demo_docs/
→ 按标题和段落切分文档
→ 生成 chunks
→ 为每个 chunk 生成 Embedding
→ 写入 ChromaDB
→ 建立 BM25 关键词索引
```

首次生成 Embedding 时可能需要联网下载默认模型，但不会消耗 Chat 模型 Token。Docker 方式将数据保存在 Docker 数据卷中；本地持久化方式将数据保存在 `data/chroma/`；已有服务则使用对应服务的存储。以后再次启动会复用非空知识库，不会因为 `data/demo_docs/` 中的文件发生变化而自动重新索引。


### 检查服务与知识库

无论使用 Docker 还是本地运行，API 默认地址都是：

```text
http://127.0.0.1:8000
```

检查服务和知识库：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/knowledge/stats
```

使用本地 ChromaDB 时，`/health` 中的 `knowledge_base.mode` 应为：

```text
local
```

使用 Docker 中的 ChromaDB 服务时，应为：

```text
server
```

连接已有 ChromaDB 服务时也会显示 `server`。

`/knowledge/stats` 返回的 `total_chunks` 大于 `0`，表示知识文档已经完成切分、Embedding 和入库。

验证知识检索：

```bash
curl -G http://127.0.0.1:8000/knowledge/search \
  --data-urlencode 'query=What is the refund policy?' \
  --data-urlencode 'top_k=3'
```

如果返回退款政策相关片段，说明 RAG 入库和检索链路已经可以工作。

### 查看完整 API 文档

后端启动后，浏览器打开：

[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

这是 FastAPI 自动生成的交互式 API 文档，可以查看 Arclume 对外提供的全部 HTTP 接口、请求字段和响应结构，也可以点击 `Try it out` 直接发送请求。主要接口包括：

- `POST /chat`：发送客服消息；
- `GET /health`：检查模型、Memory、知识库和其他组件状态；
- `GET /knowledge/search`：单独测试知识检索；
- `POST /knowledge/add`、`POST /knowledge/upload`：添加知识内容；
- `GET /knowledge/stats`：查看知识库中的 chunk 数量；
- `GET /skills`：查看当前加载的 Skills；
- `GET /traces/{request_id}`：查看一次请求的处理过程；
- `GET /monitor`、`GET /metrics`：查看运行统计；
- `POST /eval/run`：运行评测。

`/docs` 是查看完整后端能力的入口；下面的 Web 界面用于更直观地体验主要功能。

### 启动 Web 界面并开始对话

后端检查通过后，在另一个终端启动前端。本机需要安装 Node.js 与 npm：

```bash
cd frontend
npm ci
npm run dev
```

浏览器打开：

```text
http://127.0.0.1:5173
```

前端默认将 `/api` 请求转发到 `http://127.0.0.1:8000`。使用前需要先确认后端 API 已经启动。

在页面中可以发送消息、继续多轮对话、查看意图与 Agent 路由、检查知识库数量、添加知识文档并运行评测入口。

### 使用 curl 调试对话与 Trace

发送聊天请求：

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "What is the refund policy?",
    "user_id": "demo-user"
  }'
```

响应中的 `message` 是最终回复；`conversation_id` 用于继续同一段对话；`request_id` 用于查询 Trace；`primary_agent`、`supporting_agents` 和 `tools_used` 可用于检查路由和工具执行。下一轮继续对话时，应再次传入相同的 `user_id` 和返回的 `conversation_id`。

查看请求 Trace：

```bash
curl http://127.0.0.1:8000/traces/your-request-id
```


### 可选：加入自己的知识文档

准备英文 `.md` 或 `.txt` 文件，在 API 启动后上传。将下面的路径换成自己电脑上的文件：

```bash
curl -X POST http://127.0.0.1:8000/knowledge/upload \
  -F 'file=@/absolute/path/to/your_policy.md'
```

API 会在本机切片、生成向量并写入 ChromaDB，同时尝试更新 BM25 索引；再用 `/knowledge/stats` 和 `/knowledge/search` 检查结果。当前上传会**加入现有知识库**，演示资料不会自动移除。修改已有文档后重新上传也不会清理旧片段；需要只保留新版内容时，应使用独立的空知识库重新索引，具体操作见[评测文档](evaluation_protocol_zh.md)。不要通过删除现有 Docker 数据卷来做演示测试。

想观察上面提到的复合问题，可以再试一条英文消息：

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"I cannot log in and I was charged twice.","user_id":"demo-user"}'
```

重点看返回的 `primary_agent`、`supporting_agents` 和 `tools_used`，再用 `request_id` 查看 Trace。这个示例可能调用多个 Agent、消耗多次模型请求；账单部分只能提供解释或下一步建议，不能把演示环境说成查到了真实支付记录。

### 停止服务

Docker Compose 方式可以运行：

```bash
docker compose down
```

该命令停止并移除容器，但不会删除 Redis 和 ChromaDB 的 Docker 数据卷。本机运行方式在 API、Redis 和前端所在终端按 `Ctrl+C` 即可停止。已有服务应按对应环境的运维方式管理。

## 验证方式与当前边界

以下检查**不调用大模型**：

```bash
python -m unittest discover -s tests -q
python -m evaluation --smoke
python -m evaluation
```

它们验证代码行为和 LLM 生成合成样例上的意图/路由表现，不等于真实客服回复质量。实际检索和端到端模型评测需要额外环境与审慎解读，具体见[评测体系与运行方法](evaluation_protocol_zh.md)。

Arclume 目前仍是工程原型，并非已部署的客服服务：订单和物流工具使用演示数据；人工升级只记录状态并给出提示，不会真的接通客服；高风险工具虽有策略判断，但 `/chat` 尚无审批后恢复执行的完整流程。演示知识库和评测样例规模较小，不能据此宣称生产准确率。Trace 保存在进程内存中，生产环境所需的鉴权与隐私保护也尚未实现。
