# 第五步：加入 Memory 和 AgentState 保存

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
│   └── llm_utils.py               # 大模型调用和历史消息传输
├── harness/
│   ├── __init__.py                 # Python 包声明
│   ├── policy.py                  # Tool 权限和风险判断
│   ├── executor.py                # Tool 执行和结果统一
│   ├── trace.py                   # Harness 事件记录
│   └── runtime.py                 # Harness 运行控制和最小循环
├── memory/
│   ├── __init__.py                 # MemoryStoreError 和包声明
│   ├── conversation_memory.py     # Redis 短期对话记忆
│   └── state_store.py             # Redis AgentState 保存
├── schemas/
│   ├── __init__.py                 # Python 包声明
│   ├── api.py                     # API 请求和响应模型
│   ├── state.py                   # AgentState 模型
│   ├── context.py                 # Context 和 ContextMessage 模型
│   └── tool.py                    # ToolCall 和 ToolResult 模型
├── docs/
│   ├── step1.md                  # 第一步记录
│   ├── step2.md                  # 第二步记录
│   ├── step3.md                  # 第三步记录
│   ├── step4.md                  # 第四步记录
│   └── step5.md                  # 第五步记录
├── .env.example                  # 环境变量模板
├── .gitignore                    # Git 忽略规则
├── .dockerignore                 # Docker 构建忽略规则
├── Dockerfile                    # 应用镜像描述，暂不测试
├── docker-compose.yml             # API、Redis 和 ChromaDB 服务编排
├── requirements.txt              # Python 依赖
└── README.md                     # 项目说明
```

## 本步目标

第四步的 Agent 每次只看到当前一条用户消息。本步加入 Redis 短期保存，让系统可以读取同一会话的最近消息，并保存当前案件的结构化 `AgentState`。

本步解决两个问题：

```text
用户之前说过什么？       → ConversationMemory
当前案件处于什么状态？   → StateStore / AgentState
```

这两个对象仍然不是同一个东西：

```text
ConversationMemory：保存对话消息，属于短期记忆
AgentState：保存当前案件的结构化状态，属于可恢复状态
Context：一次模型请求临时组装的数据，本步还没有正式 ContextBuilder
```

## 本步新增和修改的文件

```text
memory/__init__.py                    # 新增：MemoryStoreError
memory/conversation_memory.py        # 新增：Redis 短期对话记忆
memory/state_store.py                # 新增：Redis AgentState 保存
agents/customer_service_agent.py     # 修改：读取和保存 Memory / State
api/main.py                           # 修改：创建存储并生成 conversation_id
core/llm_utils.py                    # 修改：支持传入历史消息
requirements.txt                     # 修改：加入 redis 客户端
.env.example                         # 修改：将 REDIS_URL 作为当前配置
Dockerfile                            # 修改：复制新增的 Python 包
README.md                             # 修改：更新第五步状态
docs/step5.md                         # 新增：本步骤设计和测试记录
```

本步使用 Redis，但不使用 ChromaDB。ChromaDB 保留到知识库和长期语义记忆阶段。

## 一次请求的运行流程

```text
服务启动
  → LLMClient.from_environment()
  → ConversationMemory.from_url(REDIS_URL)
  → StateStore.from_url(REDIS_URL)
  → CustomerServiceAgent(llm, memory, state_store)
```

一次 `/chat` 请求：

```text
1. API 接收 ChatRequest
2. 如果没有 conversation_id，API 生成一个新的会话 ID
3. CustomerServiceAgent 读取 Redis 中的最近消息
4. CustomerServiceAgent 读取或创建 AgentState
5. 将当前用户消息写入短期 Memory
6. 将案件状态更新为 ACTIVE，并保存 State
7. LLMClient 将 system prompt、历史消息和当前消息发给模型
8. 模型返回客服回复
9. 将客服回复写入短期 Memory
10. 更新 AgentState.version 和 updated_at
11. API 返回包含 conversation_id 的 ChatResponse
```

整体文件调用关系：

```text
api/main.py
  ├─ schemas/api.py
  │    └─ ChatRequest
  │
  ├─ agents/customer_service_agent.py
  │    ├─ memory/conversation_memory.py
  │    ├─ memory/state_store.py
  │    └─ core/llm_utils.py
  │         └─ 外部模型服务
  │
  └─ schemas/api.py
       └─ ChatResponse
```

## Redis 中保存什么

### 对话消息

每个用户和会话使用一个 Redis List：

```text
arclume:conversation:{user_id}:{conversation_id}
```

每条消息保存：

```json
{
  "role": "user 或 assistant",
  "content": "消息内容",
  "created_at": "UTC 时间"
}
```

写入时使用 `LPUSH`，最新消息放在列表头部；读取时反转顺序，交给模型的历史消息保持从旧到新的时间顺序。

当前限制：

```text
最多保存最近 20 条消息
默认 TTL 为 24 小时
超过 TTL 后 Redis 自动删除
```

本步只保存用户和客服消息，不保存 system prompt。System prompt 属于 Agent 配置，不属于用户对话记忆。

### AgentState

每个用户和会话使用一个 Redis String：

```text
arclume:state:{user_id}:{conversation_id}
```

值是 `AgentState.model_dump_json()` 的结果，包含：

```text
user_id
conversation_id
status
intent
entities
active_agent
needs_human
pending_approval
version
updated_at
```

当前只做以下状态操作：

```text
没有状态 → 创建 AgentState
开始处理 → status = ACTIVE
处理完成 → version + 1，更新 updated_at
```

更复杂的 `WAITING_FOR_APPROVAL`、`ESCALATED` 和 `RESOLVED` 状态，会在真实 Tool、人工审批和 Router 加入后使用。

## 重要文件和代码结构

### `memory/conversation_memory.py`

职责：只负责短期对话消息的 Redis 读写，不负责模型调用，也不负责判断业务状态。

类和同层结构：

```text
ConversationMemory
- _redis：异步 Redis 客户端
- max_messages：每个会话保留的最大消息数，默认 20
- ttl_seconds：消息过期时间，默认 86400 秒
- __init__()：接收 Redis 客户端和存储限制
- from_url()：根据 REDIS_URL 创建实例
- add_message()：写入一条 ContextMessage
- get_messages()：读取最近消息并恢复时间顺序
- clear()：删除一个会话的短期记忆
- close()：关闭 Redis 连接
- _key()：生成 Redis Key
```

依赖：Redis 异步客户端、`schemas.context.ContextMessage`。

被谁调用：`agents/customer_service_agent.py`。

这里使用 `ContextMessage` 作为消息格式，是为了让 Memory 读取出来的消息可以直接转换成模型历史消息。但这不表示 Memory 等于 Context；Memory 是保存的数据，Context 是以后临时组装的请求材料。

### `memory/state_store.py`

职责：把 `AgentState` 序列化到 Redis，并在下一次请求时恢复。

类和同层结构：

```text
StateStore
- _redis：异步 Redis 客户端
- ttl_seconds：状态过期时间，默认 86400 秒
- __init__()：接收 Redis 客户端和 TTL
- from_url()：根据 REDIS_URL 创建实例
- get()：读取一个案件状态
- get_or_create()：读取状态，不存在时创建新状态
- save()：保存 AgentState JSON
- delete()：删除一个案件状态
- close()：关闭 Redis 连接
- _key()：生成 Redis Key
```

依赖：Redis 异步客户端、`schemas.state.AgentState`。

被谁调用：`agents/customer_service_agent.py`。

`StateStore` 只负责保存和恢复，不负责决定状态应该如何变化。当前最小的状态更新由 Agent 完成，后面可以把状态转换规则集中到专门的状态逻辑中。

### `agents/customer_service_agent.py`

职责：在一次客服请求中协调 Memory、State 和 LLMClient。

主要属性：

```text
llm：模型调用客户端
system_prompt：客服 Agent 的固定指令
memory：ConversationMemory
state_store：StateStore
```

主要方法：

```text
respond()
- 清理和检查用户消息
- 读取历史消息
- 保存用户消息
- 读取或创建 AgentState
- 调用 LLMClient
- 保存客服回复
- 保存更新后的 AgentState
```

当前 Agent 仍然没有 ContextBuilder，所以历史消息直接作为 `LLMClient.chat()` 的 `history` 参数传输。这是第五步的临时实现；第六步会把用户消息、State、Memory 和其他材料统一交给 ContextBuilder 组装。

### `core/llm_utils.py`

本步新增了可选的 `history` 参数：

```python
LLMClient.chat(
    message,
    system_prompt=None,
    history=None,
)
```

最终发送给兼容接口的消息顺序是：

```text
system prompt
  → 历史 user / assistant 消息
  → 当前 user 消息
```

`LLMClient` 仍然不负责读取 Redis，也不负责决定保存什么。它只负责把已经准备好的消息发送给模型。

### `api/main.py`

本步启动时新增三个共享资源：

```text
app.state.llm
app.state.memory
app.state.state_store
```

然后使用它们创建：

```text
app.state.agent
```

如果请求没有传 `conversation_id`，API 使用 UUID 创建新的会话 ID，并把这个 ID 返回给客户端。客户端下一次请求应继续携带这个 ID，系统才能读取同一个会话的历史。

如果 Redis 不可用，MemoryStore 会抛出 `MemoryStoreError`，API 返回 503，而不是假装记忆已经保存成功。

## State、Memory 和 Context 的关系

第五步之后，三者的关系是：

```text
Redis Memory
  └─ 保存最近的对话消息

Redis StateStore
  └─ 保存当前案件的结构化 AgentState

Context
  └─ 仍然只是 schemas 中定义的临时结构
  └─ 正式组装逻辑等第六步 ContextBuilder
```

本步先让 Memory 进入模型请求，让客服 Agent 能看见之前的对话；State 先完成保存和恢复，但还不会被拼接成复杂 Prompt。这样可以把“存储问题”和“上下文编排问题”分开完成。

## 本步暂时不做

- 不做 ChromaDB 情景记忆；
- 不做用户画像；
- 不做历史对话语义检索；
- 不做自动摘要和记忆压缩；
- 不做正式 ContextBuilder；
- 不做 Skills；
- 不做真实业务 Tool；
- 不做多 Agent 和 Router；
- 不做 Checkpoint 恢复流程；
- 不调用真实模型进行测试。

## 终端测试

先安装当前依赖：

```bash
python -m pip install -r requirements.txt
```

执行编译检查：

```bash
python -m compileall api agents core harness memory schemas
```

可以使用下面的临时 FakeRedis 测试 Memory 和 StateStore。这个测试不需要启动 Redis，也不调用模型：

```bash
python - <<'PY'
import asyncio
import json

from memory.conversation_memory import ConversationMemory
from memory.state_store import StateStore
from schemas.context import ContextMessage
from schemas.state import AgentState


class FakeRedis:
    def __init__(self):
        self.lists = {}
        self.values = {}

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    async def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start:end + 1]

    async def expire(self, key, seconds):
        pass

    async def lrange(self, key, start, end):
        return self.lists.get(key, [])[start:end + 1]

    async def setex(self, key, seconds, value):
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.lists.pop(key, None)
        self.values.pop(key, None)

    async def aclose(self):
        pass


async def main():
    redis = FakeRedis()
    memory = ConversationMemory(redis)
    states = StateStore(redis)

    await memory.add_message("user-1", "conversation-1", ContextMessage(role="user", content="hello"))
    messages = await memory.get_messages("user-1", "conversation-1")
    assert messages[0].content == "hello"

    state = AgentState(user_id="user-1", conversation_id="conversation-1")
    await states.save(state)
    restored = await states.get("user-1", "conversation-1")
    assert restored is not None
    assert restored.conversation_id == "conversation-1"

    print({"message": messages[0].model_dump(), "state": restored.model_dump()})


asyncio.run(main())
PY
```

预期结果中应该看到一条消息和一个恢复成功的 `AgentState`。

如果要启动 API 的健康接口，仍然可以执行：

```bash
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

但完整的 `/chat` 请求需要同时满足：

```text
- Redis 已启动并且 REDIS_URL 正确；
- LLM_API_KEY、LLM_BASE_URL 和 LLM_MODEL 已配置。
```

## 完成标准

- `memory/` 目录建立完成；
- ConversationMemory 可以保存和读取最近消息；
- StateStore 可以保存和恢复 AgentState；
- Redis Key 按用户和会话隔离；
- 消息和状态都有 TTL；
- Agent 可以在模型请求前读取历史消息；
- Agent 可以在模型请求后保存用户消息和客服回复；
- AgentState 会保存当前 Agent 和版本信息；
- 没有把 Memory、State 和 Context 混成同一个对象；
- 无 Redis、无模型的测试通过；
- Dockerfile 已包含新增的 Python 包路径，但 Docker 仍未实际验证。

## 下一步连接关系

```text
当前第五步：
API
  → Agent
  → Redis Memory / Redis State
  → LLMClient
  → 回复并保存

第六步：
Memory + State + 当前问题
  → ContextBuilder
  → 统一 Context
  → Agent / Model
```
