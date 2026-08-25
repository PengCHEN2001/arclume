# 第六步：建立 ContextBuilder

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
│   ├── llm_utils.py               # 大模型调用和消息传输
│   └── context_builder.py         # 统一组装一次模型请求的 Context
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
│   ├── step5.md                  # 第五步记录
│   └── step6.md                  # 第六步记录
├── .env.example                  # 环境变量模板
├── .gitignore                    # Git 忽略规则
├── .dockerignore                 # Docker 构建忽略规则
├── Dockerfile                    # 应用镜像描述，暂不测试
├── docker-compose.yml             # API、Redis 和 ChromaDB 服务编排
├── requirements.txt              # Python 依赖
└── README.md                     # 项目说明
```

## 本步目标

第五步已经可以从 Redis 读取历史消息和 `AgentState`，但这些数据还没有经过统一整理：Agent 直接把历史消息交给 `LLMClient`，`AgentState` 也没有正式进入模型请求。

本步新增 `ContextBuilder`，解决一个核心问题：

> 一次模型请求到底应该看到哪些信息，以及这些信息应该如何排列。

当前的 Context 不只是当前用户问题，还可以包含：

```text
- Agent 的 system instructions
- 当前用户问题
- 之前的 user 消息
- 之前的 assistant 消息
- AgentState
- 已经执行的 Tool 结果
- 知识库结果
- Skill 指令
```

本步只完成 Context 的正确组装，不做上下文压缩。

## 本步新增和修改的文件

```text
core/context_builder.py             # 新增：Context 组装和模型消息渲染
agents/customer_service_agent.py   # 修改：通过 ContextBuilder 调用模型
README.md                           # 修改：更新第六步状态
docs/step6.md                       # 新增：本步骤设计和测试记录
```

`schemas/context.py` 已经在第二步定义了 `Context` 和 `ContextMessage`，本步直接使用现有结构，不额外创建另一套 Context 数据格式。

## Memory、State 和 Context 的区别

```text
Memory：保存历史消息的地方
State：保存当前案件结构化状态的地方
Context：本次模型调用临时使用的材料
```

例如 Redis 中可能保存了：

```text
用户：我的包裹还没到
客服：我帮你查询一下
用户：现在怎么样了？
客服：目前还没有结果
```

同时 Redis 的 `AgentState` 可能是：

```text
status = active
active_agent = customer_service
pending_approval = false
```

ContextBuilder 会把这些内容组装成模型本次真正需要看到的内容。Context 本身不会长期保存到 Redis。

## 一次请求的运行流程

```text
1. API 接收用户消息
2. CustomerServiceAgent 从 Memory 读取历史消息
3. CustomerServiceAgent 从 StateStore 读取 AgentState
4. CustomerServiceAgent 保存当前用户消息
5. ContextBuilder.build() 创建 Context
6. ContextBuilder.render_system_prompt() 准备 system prompt
7. ContextBuilder.render_history() 准备 State 和历史消息
8. LLMClient 将 system prompt、history 和当前用户问题发送给模型
9. 模型返回客服回复
10. Agent 保存客服回复和更新后的 AgentState
11. API 返回 ChatResponse
```

文件调用关系：

```text
api/main.py
  ↓
agents/customer_service_agent.py
  ├─ memory/conversation_memory.py
  ├─ memory/state_store.py
  ├─ core/context_builder.py
  │    └─ schemas/context.py
  └─ core/llm_utils.py
       └─ 外部模型服务
```

## Context 的内容排列

本步使用以下顺序：

```text
system prompt
  ↓
当前 AgentState
  ↓
Skill 指令，如果未来传入
  ↓
知识库结果，如果未来传入
  ↓
之前的 user / assistant 消息
  ↓
Tool 结果，如果未来传入
  ↓
当前用户问题
```

当前用户问题不会由 `ContextBuilder.render_history()` 重复放入历史，因为 `LLMClient` 会把当前问题追加在历史消息之后。

这样模型能同时看到：

```text
之前发生过什么
系统已经做过什么
当前案件处于什么状态
用户现在又提出了什么问题
```

## 重要文件和代码结构

### `core/context_builder.py`

职责：把已经读取到的各种上下文材料统一放进 `Context`，并渲染成模型可以使用的消息格式。

这个类暂时不负责：

```text
- 读取 Redis
- 查询 ChromaDB
- 调用大模型
- 压缩上下文
- 生成历史摘要
```

类和方法：

```text
ContextBuilder
- system_instructions：固定的 Agent 指令
- __init__()：保存 system instructions
- build()：创建一个 Context
- render_system_prompt()：渲染 system prompt
- render_history()：将 State、历史消息和 Tool 结果转成模型 history
- _json_text()：统一序列化结构化内容
```

`build()` 接收：

```text
- user_message：当前用户问题
- conversation_history：历史 user / assistant 消息
- state：当前 AgentState
- knowledge_results：预留给知识库结果
- skill_instructions：预留给 Skill 指令
- tool_results：预留给 Tool 结果
- metadata：其他请求级信息
```

`render_history()` 的重要规则：

```text
当前用户问题不放入 history
AgentState 以结构化 JSON 放入 system message
历史对话保持原始 user / assistant 角色
ToolResult 以 tool message 形式放入
```

### `agents/customer_service_agent.py`

本步新增了一个属性：

```text
context_builder：负责构建当前模型请求的 ContextBuilder
```

本步的 `respond()` 流程变成：

```text
清理用户消息
  ↓
读取 Memory
  ↓
读取 AgentState
  ↓
保存当前用户消息
  ↓
ContextBuilder.build()
  ↓
ContextBuilder 渲染消息
  ↓
LLMClient.chat()
  ↓
保存客服回复和 State
```

Agent 仍然是单 Agent，没有加入 Router、Skill 或真实 Tool。

### `schemas/context.py`

本步继续使用原有结构：

```text
ContextMessage
- role：system、user、assistant 或 tool
- content：消息内容

Context
- user_message：当前用户问题
- conversation_history：历史消息
- state：当前 AgentState
- system_instructions：系统指令
- knowledge_results：知识库结果
- skill_instructions：Skill 指令
- tool_results：Tool 结果
- metadata：其他信息
```

这里已经提前预留了知识库、Skill 和 Tool 的位置，但本步不主动填充它们。

### `core/llm_utils.py`

本步继续使用已有的调用方式：

```python
LLMClient.chat(
    message,
    system_prompt=system_prompt,
    history=history,
)
```

`LLMClient` 只负责传输消息，不再自己决定哪些消息应该进入 Context。选择和排列由 `ContextBuilder` 完成。

## 本步明确不做上下文压缩

本步暂时不加入：

```text
- Token 精确计算
- 上下文长度百分比阈值
- 自动摘要
- rolling summary
- LLMLingua
- 长文档分块
- 历史消息语义检索
- 删除单条过长用户消息
```

当前消息限制仍然由第五步的 Redis `max_messages=20` 粗略控制，但这只是短期 Memory 的存储上限，不是完整的 Context 压缩方案。

以后如果真实使用中出现上下文过长，再单独增加 Context Budget 和 Context Compression。压缩时应该优先压缩较早的已完成对话，不能直接截断当前用户问题、AgentState 或关键 Tool 结果。

## 当前请求示例

假设 Redis 中已有：

```text
user：我的订单还没到
assistant：我帮你查询一下
```

当前 State：

```json
{
  "status": "active",
  "active_agent": "customer_service",
  "pending_approval": false
}
```

当前用户又发送：

```text
现在有结果了吗？
```

ContextBuilder 产生的模型输入大致是：

```text
system：客服 Agent 的基础指令

system：[Current case state]
{"status":"active","active_agent":"customer_service", ...}

user：我的订单还没到
assistant：我帮你查询一下

user：现在有结果了吗？
```

第六步完成后，模型第一次能够同时看到历史对话和当前 AgentState。后续加入真实 Tool 后，Tool 结果也会放在相同的 Context 中。

## 终端测试

执行编译检查：

```bash
python -m compileall api agents core harness memory schemas
```

执行不连接 Redis、不调用模型的 ContextBuilder 测试：

```bash
python - <<'PY'
from core.context_builder import ContextBuilder
from schemas.context import ContextMessage
from schemas.state import AgentState, AgentStatus


builder = ContextBuilder(["You are a customer-service assistant."])
state = AgentState(
    user_id="user-1",
    conversation_id="conversation-1",
    status=AgentStatus.ACTIVE,
    active_agent="customer_service",
)
context = builder.build(
    "What is the latest update?",
    conversation_history=[
        ContextMessage(role="user", content="My order is late."),
        ContextMessage(role="assistant", content="I will check it."),
    ],
    state=state,
)
history = builder.render_history(context)

assert context.user_message == "What is the latest update?"
assert history[0]["role"] == "system"
assert history[-1]["role"] == "assistant"
assert "active_agent" in history[0]["content"]
print({"context_user_message": context.user_message, "history_messages": len(history)})
PY
```

预期结果：

```text
context_user_message = What is the latest update?
history_messages = 3
```

这个测试只验证 Context 的组装和排序，不会调用 Redis 或模型。

## 完成标准

- `core/context_builder.py` 建立完成；
- ContextBuilder 能接收当前问题、历史消息和 AgentState；
- CustomerServiceAgent 在调用模型前使用 ContextBuilder；
- AgentState 能够进入模型 history；
- user / assistant 历史消息保持原始角色和顺序；
- 当前用户问题不会在 history 中重复出现；
- Tool、Knowledge 和 Skill 字段已经预留；
- 没有加入上下文压缩和 Token 预算逻辑；
- ContextBuilder 不负责读取数据库或调用模型；
- 无 Redis、无模型的 Context 测试通过。

## 下一步连接关系

```text
第五步：
Memory + AgentState 保存和读取

第六步：
Memory + AgentState + 当前问题
  → ContextBuilder
  → Context
  → LLMClient

第七步：
ContextBuilder 接收知识库检索结果
  → 把相关知识放入 Context
```
