# 第二步：定义统一的 API 和基础数据结构

## 目标

建立统一的 `schemas/` 数据结构，用来定义：

- API 请求和响应
- Agent 当前状态
- 一次模型请求的临时 Context
- Tool 调用和 Tool 返回结果

本步骤只定义数据结构，不保存 State、不组装 Context、不执行 Tool，也不调用真实模型 API。

## 为什么要做这一步

后面的 API、Agent、Harness、Memory 和 Tool 都需要互相传递数据。如果每个模块都自己定义字典字段，很容易出现字段名称和含义不一致的问题。

因此先建立一套共享的数据契约：

```text
API 请求和响应
        -> AgentState
        -> Context
        -> ToolCall / ToolResult
```

这里使用 Pydantic，是为了获得：

- 明确的字段类型
- 自动数据校验
- 统一的数据结构
- 后续方便保存和转换为 JSON

## 主要文件及作用

```text
schemas/              # 统一保存项目各模块共用的数据结构
├── __init__.py       # 声明 schemas 是 Python 包
├── api.py            # 定义外部 API 的请求和响应格式
├── state.py          # 定义当前客服案件的 AgentState
├── context.py        # 定义一次模型请求使用的临时 Context
└── tool.py           # 定义 ToolCall 和 ToolResult 的数据格式

api/main.py           # 使用 schemas.api 中的 ChatRequest 和 ChatResponse
README.md             # 更新项目当前阶段和新增 schemas 说明
```

其中最重要的四个文件是：

```text
api.py      -> 外部请求和响应应该长什么样
state.py    -> 当前案件状态应该保存哪些字段
context.py  -> 一次模型调用可以使用哪些上下文材料
tool.py     -> Tool 调用和返回结果应该长什么样
```

## 本步创建和修改的文件

```text
schemas/
├── __init__.py       # Python 包声明
├── api.py            # ChatRequest 和 ChatResponse
├── state.py          # AgentStatus 和 AgentState
├── context.py        # ContextMessage 和 Context
└── tool.py           # ToolCall 和 ToolResult

api/main.py           # 改为从 schemas.api 导入 API 模型
README.md             # 更新当前项目阶段
```

## 整体数据关系

```text
api/main.py
  -> schemas.api.ChatRequest
  -> core.llm_utils.LLMClient
  -> schemas.api.ChatResponse

未来的 Agent Runtime
  -> schemas.state.AgentState
  -> schemas.context.Context
  -> schemas.tool.ToolCall
  -> schemas.tool.ToolResult
```

`AgentState` 和 `Context` 的区别：

```text
AgentState：当前案件的结构化状态，未来可以保存和恢复
Context：一次模型请求临时组装的上下文材料
```

后续真正的保存和组装会放在后面的步骤：

```text
第二步：定义数据模型
第五步：加入 State 保存
第六步：加入 ContextBuilder
```

## 文件职责概览

### `schemas/api.py`

类：

```text
ChatRequest
- message：用户消息
- user_id：用户标识
- conversation_id：会话标识

ChatResponse
- message：模型回复
- model：模型名称
- conversation_id：会话标识
```

依赖：Pydantic。

调用和使用者：`api/main.py`、FastAPI 的请求解析和响应校验流程。

### `schemas/state.py`

类：

```text
AgentStatus
- NEW：新建
- ACTIVE：处理中
- WAITING_FOR_INPUT：等待用户输入
- WAITING_FOR_APPROVAL：等待人工审批
- ESCALATED：已转人工
- RESOLVED：已解决

AgentState
- user_id：用户标识
- conversation_id：会话标识
- status：当前案件状态
- intent：当前意图
- entities：识别出的实体
- active_agent：当前负责的 Agent
- needs_human：是否需要人工介入
- pending_approval：是否等待审批
- version：状态版本
- updated_at：更新时间
```

依赖：Pydantic、Python 的时间和枚举类型。

未来使用者：State Store、Agent Runtime、Router、Harness 和 Memory。

本步骤只定义模型，不实现保存逻辑。

### `schemas/context.py`

类：

```text
ContextMessage
- role：消息角色
- content：消息内容

Context
- user_message：当前用户问题
- conversation_history：对话历史
- state：当前 AgentState 快照
- system_instructions：系统指令
- knowledge_results：知识库结果
- skill_instructions：Skill 指令
- tool_results：Tool 结果
- metadata：其他上下文信息
```

依赖：Pydantic、`AgentState`、`ToolResult`。

未来使用者：ContextBuilder、Agent Runtime 和模型 Prompt 组装流程。

本步骤还没有 ContextBuilder。

### `schemas/tool.py`

类：

```text
ToolCall
- call_id：本次调用的唯一标识
- tool_name：Tool 名称
- arguments：Tool 参数
- requested_by：请求来源

ToolResult
- call_id：对应的调用标识
- tool_name：Tool 名称
- success：是否成功
- data：返回数据
- error：错误信息
- requires_approval：是否需要审批
- duration_ms：执行耗时
```

依赖：Pydantic。

未来使用者：Harness Runtime、Tool Executor、Agent Runtime 和审计逻辑。

权限判断、参数校验、重试、超时和人工审批不在本步骤实现。

### `schemas/__init__.py`

只负责声明 `schemas` 是 Python 包，没有类和业务逻辑。

## `api/main.py` 的变化

API 数据模型从入口文件中独立出来：

```text
之前：
api/main.py 自己定义 ChatRequest 和 ChatResponse

现在：
api/main.py 从 schemas.api 导入 ChatRequest 和 ChatResponse
```

接口行为没有改变，这次只是把共享的数据结构放到了统一目录中。

## 执行顺序

1. 创建 `schemas/` 目录和文件。
2. 定义 Pydantic 模型及其字段。
3. 修改 `api/main.py`，从 `schemas.api` 导入 API 模型。
4. 执行语法和导入检查。
5. 执行本地健康检查。
6. 不保存 State、不组装 Context、不执行 Tool、不调用真实模型。

## 终端测试

执行 Python 编译检查：

```bash
python -m compileall api core schemas
```

检查模型是否可以导入和转换：

```bash
python -c "from schemas.api import ChatRequest; from schemas.state import AgentState; from schemas.context import Context; from schemas.tool import ToolCall; request=ChatRequest(message='hello'); state=AgentState(conversation_id='demo'); context=Context(user_message='hello', state=state); call=ToolCall(call_id='call-1', tool_name='demo'); print(request.model_dump()); print(context.model_dump()); print(call.model_dump())"
```

启动本地 API：

```bash
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

再打开另一个终端执行：

```bash
curl -i http://127.0.0.1:8000/health
```

预期状态：

```text
HTTP/1.1 200 OK
```

这些测试不会调用真实模型，也不会消耗 API Token。

## 完成标准

- `schemas/` 目录和四个数据模型文件已经建立。
- API 请求和响应模型不再定义在 `api/main.py` 中。
- `AgentState`、`Context`、`ToolCall` 和 `ToolResult` 可以正常导入和转换。
- FastAPI 的 `/health` 仍然返回 200。
- 本步骤没有加入 State 保存、Context 组装、Tool 执行或 Agent Loop。
