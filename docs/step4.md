# 第四步：实现最简单的单 Agent 客服对话

## 当前项目目录

```text
arclume/
├── api/
│   ├── __init__.py                 # Python 包声明
│   └── main.py                    # FastAPI 入口和 HTTP 接口
├── agents/
│   ├── __init__.py                 # Python 包声明
│   └── customer_service_agent.py  # 单 Agent 客服逻辑
├── core/
│   ├── __init__.py                 # Python 包声明
│   └── llm_utils.py               # 大模型调用封装
├── harness/
│   ├── __init__.py                 # Python 包声明
│   ├── policy.py                  # Tool 权限和风险判断
│   ├── executor.py                # Tool 执行和结果统一
│   ├── trace.py                   # Harness 事件记录
│   └── runtime.py                 # Harness 运行控制和最小循环
├── schemas/
│   ├── __init__.py                 # Python 包声明
│   ├── api.py                     # API 请求和响应模型
│   ├── state.py                   # AgentState 模型
│   ├── context.py                 # Context 模型
│   └── tool.py                    # ToolCall 和 ToolResult 模型
├── docs/
│   ├── step1.md                  # 第一步记录
│   ├── step2.md                  # 第二步记录
│   ├── step3.md                  # 第三步记录
│   └── step4.md                  # 第四步记录
├── .env.example                  # 环境变量模板
├── .gitignore                    # Git 忽略规则
├── .dockerignore                 # Docker 构建忽略规则
├── Dockerfile                    # 应用镜像描述，暂不测试
├── docker-compose.yml             # 服务编排，暂不启动
├── requirements.txt              # Python 依赖
└── README.md                     # 项目说明
```

## 本步目标

前面已经有了 FastAPI、LLMClient、统一数据结构和 Harness 边界，但 `/chat` 之前仍然是 API 直接调用 LLMClient。

本步新增一个最简单的客服 Agent，让 API 不再直接负责模型调用，而是把用户消息交给 Agent：

```text
POST /chat
  → ChatRequest
  → CustomerServiceAgent
  → LLMClient
  → ChatResponse
```

这一步只实现单 Agent、单次模型请求。先把 Agent 的职责和入口固定下来，后面再逐步向它加入 Memory、ContextBuilder、Skill、Tool、Router 和多 Agent 协作。

## 本步新增和修改的文件

```text
agents/__init__.py                    # 新增：声明 agents 是 Python 包
agents/customer_service_agent.py     # 新增：单 Agent 客服实现
api/main.py                           # 修改：创建 Agent，并让 /chat 调用 Agent
README.md                             # 修改：记录第四步已经完成的功能
docs/step4.md                         # 新增：本步骤设计和测试记录
```

`core/llm_utils.py` 不需要新增模型供应商逻辑。它已经支持：

```python
LLMClient.chat(message, system_prompt=None)
```

第四步只使用这个已有的 `system_prompt` 参数，把客服 Agent 的基础行为传给模型。

## 一次请求的运行流程

```text
1. 客户端向 /chat 发送 ChatRequest
2. FastAPI 校验 message、user_id 和 conversation_id
3. API 从 app.state 取出已经创建好的 CustomerServiceAgent
4. API 调用 agent.respond(payload.message)
5. Agent 清理用户消息并检查是否为空
6. Agent 将客服 system prompt 和用户消息交给 LLMClient
7. LLMClient 根据环境变量调用配置好的模型服务
8. 模型返回文本
9. Agent 将文本返回给 API
10. API 封装成 ChatResponse
```

当前实际链路是：

```text
【一次 POST /chat 请求】

客户端
  │
  ▼
api/main.py
  │
  ├─ 接收 POST /chat
  │
  ├─ schemas/api.py
  │    └─ ChatRequest 校验请求字段
  │
  ├─ 获取 app.state.agent
  │
  ▼
agents/customer_service_agent.py
  │
  ├─ CustomerServiceAgent.respond()
  ├─ 清理用户消息
  ├─ 检查消息是否为空
  └─ 添加 system_prompt
  │
  ▼
core/llm_utils.py
  │
  ├─ LLMClient.chat()
  ├─ 读取 model、base_url、api_key
  ├─ 组装 system message + user message
  └─ 发送 HTTP 请求
  │
  ▼
外部模型服务
  │
  └─ 返回模型文本
  │
  ▼
core/llm_utils.py
  └─ 提取并返回回复文本
  │
  ▼
agents/customer_service_agent.py
  └─ 返回客服回复
  │
  ▼
api/main.py
  │
  └─ 创建 ChatResponse
       │
       ▼
schemas/api.py
  └─ 校验响应格式
       │
       ▼
客户端收到 JSON 回复
```

本步还没有历史消息，所以每次请求都是一次独立的单轮对话。
当前第四步不会经过：harness/ memory/ context_builder/ skills/ knowledge_base/ 多 Agent Router

## 重要文件和代码结构

### `agents/customer_service_agent.py`

职责：代表第一个客服 Agent，负责把客服行为说明和用户问题交给大模型。

类和同层结构：

```text
DEFAULT_SYSTEM_PROMPT
- 当前客服 Agent 的基础行为指令
- 规定回答风格、能力边界和无法处理时的处理方式

CustomerServiceAgent
- name：Agent 名称
- llm：共享的 LLMClient
- system_prompt：当前 Agent 的系统指令
- __init__()：注入 LLMClient 和 system prompt
- respond()：处理一条用户消息并返回文本
```

`respond()` 的运行思路：

```text
接收 message
  → 去除首尾空白
  → 检查是否为空
  → 调用 LLMClient.chat()
  → 返回模型文本
```

依赖：`core.llm_utils.LLMClient`。

被谁调用：`api/main.py`。

当前 Agent 暂时没有：

```text
- AgentState
- Memory
- ContextBuilder
- Skill
- Knowledge Base
- ToolCall
- 多 Agent 路由
```

这些不是被忽略，而是分别在后面的步骤接入。这里先保留一个稳定的 `respond()` 入口，方便后续在 Agent 内部增加上下文和决策流程。

### `core/llm_utils.py`

职责：负责和模型供应商进行 HTTP 通信，不负责客服业务判断。

第四步使用的结构：

```text
LLMSettings
- provider：模型供应商标签
- api_key：API 密钥
- base_url：模型服务地址
- model：模型名称
- timeout_seconds：请求超时时间

LLMClient
- settings：模型配置
- _http：复用的异步 HTTP 客户端
- from_environment()：从环境变量创建客户端
- chat()：发送用户消息和可选 system prompt
- close()：关闭 HTTP 客户端
```

本步没有把 DeepSeek 写死在代码里。实际使用哪个模型，由以下环境变量决定：

```text
LLM_PROVIDER
LLM_API_KEY
LLM_BASE_URL
LLM_MODEL
LLM_TIMEOUT_SECONDS
```

因此当前可以接入 DeepSeek，也可以以后切换到其他兼容接口的模型，不需要修改 `CustomerServiceAgent`。

### `api/main.py`

职责：管理 HTTP 生命周期，把外部请求交给 CustomerServiceAgent。

本步的重要变化：

```text
应用启动
  → 创建 LLMClient
  → 使用这个 LLMClient 创建 CustomerServiceAgent
  → 保存到 app.state
```

主要对象：

```text
app.state.llm
- 整个 API 进程复用的 LLMClient

app.state.agent
- 整个 API 进程复用的 CustomerServiceAgent
```

主要函数：

```text
lifespan()
- 启动时创建 LLMClient 和 CustomerServiceAgent
- 关闭时释放 LLMClient 的 HTTP 连接

health()
- 返回服务和模型配置状态

chat()
- 接收 ChatRequest
- 调用 CustomerServiceAgent.respond()
- 捕获模型配置或请求错误
- 返回 ChatResponse
```

本步之后，`api/main.py` 不再直接调用 `llm.chat(payload.message)`，而是调用：

```python
answer = await agent.respond(payload.message)
```

这样 API 层只负责 HTTP，客服行为由 Agent 负责。

## Harness 在本步的位置

第三步已经建立 Harness，但第四步还没有真实 ToolCall，因此当前普通聊天不会经过 Tool Executor：

```text
当前：
CustomerServiceAgent
  → LLMClient
  → 最终文本
```

以后当 Agent 需要查询订单或创建工单时，流程才会变成：

```text
CustomerServiceAgent
  → Agent 决策
  → HarnessRuntime
  → Policy
  → Executor
  → ToolResult
  → Agent 继续处理
```

Harness 负责控制 Tool 执行，不需要拦截每一次普通文本生成。第四步先完成单 Agent 的基本职责，后面加入 Tool Call 时再连接 Harness Loop。

## 本步暂时不做

- 不做 Memory 和 Redis 保存；
- 不做 ContextBuilder；
- 不做知识库和 RAG；
- 不做 Skills；
- 不做真实业务 Tool；
- 不做 Tool Call 解析；
- 不做多 Agent 和 Router；
- 不做人工审批流程；
- 不做真实模型测试。

## 终端测试

先执行编译检查：

```bash
python -m compileall api core schemas harness agents
```

不调用真实模型，直接使用假的 LLMClient 测试 Agent：

```bash
python -c "import asyncio; from agents.customer_service_agent import CustomerServiceAgent; fake=type('FakeLLM', (), {'chat': lambda self, message, system_prompt=None: asyncio.sleep(0, result='fake customer reply')})(); agent=CustomerServiceAgent(fake); print(asyncio.run(agent.respond('hello')))"
```

预期输出：

```text
fake customer reply
```

这个测试可以验证：

```text
- agents.customer_service_agent 可以导入；
- Agent 可以接收用户消息；
- Agent 会调用注入的 LLMClient；
- Agent 可以返回模型文本；
- 测试没有消耗真实 API Token。
```

启动 HTTP 服务后，可以继续测试健康接口：

```bash
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

另开一个终端：

```bash
curl -i http://127.0.0.1:8000/health
```

如果没有配置真实模型，直接调用 `/chat` 会返回配置错误，这是预期行为，不需要为了本步测试而配置或调用真实模型。

## 完成标准

- `agents/` 目录建立完成；
- `CustomerServiceAgent` 可以被正常导入；
- Agent 拥有稳定的 `respond()` 入口；
- Agent 使用 system prompt 调用 LLMClient；
- `/chat` 已经通过 Agent 处理请求；
- LLMClient 仍然保持供应商无关；
- API 启动时只创建一份共享 LLMClient 和 Agent；
- 没有提前加入 Memory、RAG、Skill、真实 Tool 或多 Agent；
- 无模型调用测试通过。

## 下一步连接关系

```text
当前第四步：
API → CustomerServiceAgent → LLMClient → 回复

后续第五步：
API → Agent → 读取和保存 Memory / State

后续第六步：
Agent → ContextBuilder → 组装临时 Context

更后面：
Agent → Harness → Tool / Knowledge / 多 Agent
```
