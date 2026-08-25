# 第三步：建立 Harness 核心边界

## 当前项目目录

```text
arclume/
├── api/
│   ├── __init__.py                 # Python 包声明
│   └── main.py                    # FastAPI 入口和当前 HTTP 接口
├── core/
│   ├── __init__.py                 # Python 包声明
│   └── llm_utils.py               # 大模型 HTTP 调用封装
├── harness/
│   ├── __init__.py                 # Python 包声明
│   ├── policy.py                  # Tool 权限和风险判断
│   ├── executor.py                # Tool 注册、执行和结果统一
│   ├── trace.py                   # Harness 运行事件记录
│   └── runtime.py                 # Harness 运行控制和最小 Agent Loop
├── schemas/
│   ├── __init__.py                 # Python 包声明
│   ├── api.py                     # API 请求和响应模型
│   ├── state.py                   # AgentState 模型
│   ├── context.py                 # Context 模型
│   └── tool.py                    # ToolCall 和 ToolResult 模型
├── docs/
│   ├── step1.md                  # 第一步记录
│   ├── step2.md                  # 第二步记录
│   └── step3.md                  # 第三步记录
├── .env.example                  # 环境变量模板
├── .gitignore                    # Git 忽略规则
├── .dockerignore                 # Docker 构建忽略规则
├── Dockerfile                    # 应用镜像描述，暂不测试
├── docker-compose.yml             # 服务编排，暂不启动
├── requirements.txt              # Python 依赖
└── README.md                     # 项目说明
```

## 本步目标

第三步不是创建新的客服 Agent，也不是马上做多 Agent、MCP、Redis 或真实业务 Tool。

本步先建立一个清晰的内部控制边界：模型或 Agent 只能提出 `ToolCall`，不能直接访问订单系统、数据库或外部 API。所有 Tool 调用先经过 Harness，再决定是否执行。

核心关系是：

```text
Agent / Model 提出 ToolCall
        ↓
Harness Runtime 接收
        ↓
Policy 判断是否允许
        ↓
Executor 执行 Tool
        ↓
统一返回 ToolResult
        ↓
TraceRecorder 记录过程
```

这样做的目的，是把“模型决定做什么”和“系统实际允许做什么”分开。以后加入订单查询、退款、创建工单等 Tool 时，不需要让每个 Agent 自己重复实现权限、超时和错误处理。

## 本步新增内容

```text
harness/policy.py       # 判断 Tool 是否存在、启用、允许当前 Agent 使用，以及是否需要审批
harness/executor.py     # 注册 Tool，执行 handler，处理参数、超时、重试和结果转换
harness/trace.py        # 在内存中记录一次运行的结构化事件
harness/runtime.py      # 连接 Policy、Executor、Trace，并提供最小循环
```

`schemas/tool.py` 中已有的 `ToolCall` 和 `ToolResult` 会继续作为 Harness 内部统一的数据格式。本步没有修改它们。

## 一次运行流程

第三步可以用一个假的决策函数模拟未来的模型：

```text
1. 决策函数返回 ToolCall
2. HarnessRuntime 接收到 ToolCall
3. ToolPolicy 检查 Tool 是否存在、是否启用、风险是否需要审批
4. 如果不允许，直接生成失败的 ToolResult
5. 如果需要审批，生成 requires_approval=True 的 ToolResult，并暂停循环
6. 如果允许，ToolExecutor 执行对应 handler
7. Executor 处理参数校验、超时、重试和结果统一
8. ToolResult 放回临时运行上下文
9. 决策函数再次获得上下文，可以继续调用 Tool 或返回最终文字
10. TraceRecorder 记录关键事件
```

最小循环的形态是：

```text
决策函数
  ├── 返回最终文字 → Runtime 完成
  └── 返回 ToolCall
        ↓
      Policy
        ├── DENY → 返回失败结果
        ├── REQUIRE_APPROVAL → 暂停等待审批
        └── ALLOW → Executor 执行
                         ↓
                    ToolResult 回到决策函数
```

这里的“决策函数”暂时不是实际大模型调用，而是一个可以注入的函数。这样可以不花费 API Token，先测试 Harness 的边界和循环是否正确。

## 重要文件和代码结构

### `harness/policy.py`

职责：对 ToolCall 做确定性的权限和风险判断，不执行 Tool，也不调用大模型。

类和同层结构：

```text
ToolRiskLevel
- LOW：低风险，例如查询信息
- MEDIUM：中风险，例如创建工单
- HIGH：高风险，例如退款或修改账户

PolicyAction
- ALLOW：允许执行
- DENY：拒绝执行
- REQUIRE_APPROVAL：需要人工审批

PolicyTool
- 一个协议类型，只声明 Policy 需要读取的 Tool 属性

PolicyResult
- action：Policy 决定
- reason：决定原因
- risk_level：Tool 风险等级
- allowed：判断是否可以直接执行的属性

ToolPolicy
- approval_required_levels：哪些风险等级需要审批
- evaluate()：检查一个 ToolCall
```

依赖：`schemas.tool.ToolCall`、`schemas.state.AgentState`，以及 `ToolDefinition` 提供的几个元数据属性。

被谁调用：`harness/runtime.py`。

当前规则：

```text
Tool 不存在       → DENY
Tool 已关闭       → DENY
Agent 没有权限    → DENY
高风险 Tool       → REQUIRE_APPROVAL
其他已注册 Tool   → ALLOW
```

本步的人工审批只是一个暂停结果，还没有审批 API、审批页面或恢复流程。真正的审批流程属于后续业务功能。

### `harness/executor.py`

职责：保存可执行 Tool，执行被允许的 Tool，并把各种 handler 返回值统一成 `ToolResult`。

类和同层结构：

```text
ToolHandler
- Tool 实际执行函数的类型
- 接收 arguments 和 context
- 可以是同步函数，也可以是异步函数

ToolDefinition
- name：Tool 名称
- description：Tool 说明
- handler：实际执行函数
- input_schema：输入参数的 JSON Schema
- risk_level：风险等级
- timeout_seconds：超时时间
- max_retries：最大重试次数
- allowed_agents：允许使用的 Agent
- enabled：是否启用

ToolExecutor
- _tools：按名称保存 ToolDefinition
- register()：注册 Tool
- unregister()：移除 Tool
- get()：获取一个 Tool
- list_tools()：查看已经注册的 Tool
- execute()：执行一次 ToolCall
- _validate_arguments()：检查必要参数和基础类型
- _run_handler()：运行同步或异步 handler
- _normalize_result()：统一转换为 ToolResult
```

依赖：`schemas.tool.ToolCall`、`schemas.tool.ToolResult`、`harness.policy.ToolRiskLevel`。

被谁调用：`harness/runtime.py`。未来真实的业务 Tool 会通过 `ToolDefinition` 注册到这里。

当前没有真实业务 Tool。测试时只使用临时的假 Tool，避免连接订单系统或消耗模型 Token。

### `harness/trace.py`

职责：记录 Harness 运行过程中的关键事件。目前只保存在内存中，不写 Redis、数据库或文件。

类和同层结构：

```text
TraceEventType
- RUNTIME_STARTED：运行开始
- DECISION_RECEIVED：收到模型或 Agent 的决定
- POLICY_EVALUATED：Policy 完成判断
- TOOL_EXECUTION_FINISHED：Tool 执行完成
- RUNTIME_COMPLETED：正常返回最终结果
- RUNTIME_STOPPED：因为审批或最大循环次数停止
- RUNTIME_FAILED：运行出错

TraceEvent
- event_id：事件 ID
- event_type：事件类型
- timestamp：事件时间
- call_id：关联的 Tool 调用 ID
- tool_name：关联的 Tool 名称
- data：其他结构化信息

TraceRecorder
- _events：当前运行的内存事件列表
- record()：记录一条事件
- events()：读取事件副本
- clear()：清空事件
```

依赖：Pydantic、Python 时间和 UUID 类型。

被谁调用：`harness/runtime.py`。

当前记录 Tool 参数的字段名，而不是完整参数值，先减少敏感信息进入日志的风险。以后接入审计和监控时，再决定哪些字段可以持久化。

### `harness/runtime.py`

职责：把决策、Policy、Executor 和 Trace 串成一个最小的 Harness 运行过程。

类和同层结构：

```text
Decision
- 可以是最终回复字符串
- 也可以是 schemas.tool.ToolCall

DecisionProvider
- 未来由 Agent 或模型适配器提供的决策函数

RuntimeStatus
- COMPLETED：返回最终文字
- WAITING_FOR_APPROVAL：等待人工审批
- MAX_ITERATIONS：达到最大循环次数
- FAILED：运行出错

RuntimeOutcome
- status：运行状态
- message：最终回复
- tool_results：本次运行产生的 Tool 结果
- iterations：执行了几轮
- error：错误信息

HarnessRuntime
- policy：ToolPolicy
- executor：ToolExecutor
- tracer：TraceRecorder
- max_iterations：最大循环次数
- handle_tool_call()：检查并执行一个 ToolCall
- run()：运行最小决策循环
```

依赖：`harness.policy`、`harness.executor`、`harness.trace`、`schemas.state`、`schemas.tool`。

被谁调用：本步先由测试代码直接调用。第四步实现客服 Agent 后，客服 Agent 会把模型的决策交给这里。

## 当前 API 的状态

本步暂时不修改 `api/main.py` 的 `/chat` 业务流程。当前请求仍然是：

```text
POST /chat
  → LLMClient
  → ChatResponse
```

原因是第四步才创建最简单的客服 Agent。到那时，API 才会改成：

```text
POST /chat
  → CustomerServiceAgent
  → Context / Agent decision
  → HarnessRuntime
  → Tool 或最终回复
```

因此，第三步已经把边界准备好，但不会为了接入还不存在的 Agent 而提前改写当前 API。

## 本步暂时不做

- 不接入 MCP；
- 不创建订单查询、物流查询、退款等真实 Tool；
- 不连接 Redis、ChromaDB 或外部业务 API；
- 不实现客服 Agent；
- 不实现真正的大模型 Tool Call 解析；
- 不做多 Agent 路由；
- 不实现完整人工审批页面和恢复接口；
- 不把 Trace 持久化到数据库；
- 不进行真实模型调用。

## 终端测试

先执行语法检查：

```bash
python -m compileall api core schemas harness
```

再执行一个不调用模型的 Harness 测试：

```bash
python -c "import asyncio; from harness.executor import ToolDefinition, ToolExecutor; from harness.runtime import HarnessRuntime; from schemas.tool import ToolCall; tool=ToolDefinition(name='demo_echo', description='Echo test tool', handler=lambda arguments, context: {'echo': arguments['message']}, input_schema={'type': 'object', 'required': ['message'], 'properties': {'message': {'type': 'string'}}}); runtime=HarnessRuntime(executor=ToolExecutor([tool])); calls=iter([ToolCall(call_id='call-1', tool_name='demo_echo', arguments={'message': 'hello'}), 'done']); result=asyncio.run(runtime.run(lambda context: next(calls))); print(result.model_dump()); print([event.event_type.value for event in runtime.tracer.events()])"
```

预期结果中应该看到：

```text
status = completed
tool_results 中有 demo_echo 的成功结果
trace 中包含 runtime_started、decision_received、policy_evaluated、tool_execution_finished、runtime_completed
```

如果终端不方便执行多行命令，也可以暂时只执行编译检查。这个测试不会请求任何大模型 API。

## 完成标准

- `harness/` 目录建立完成；
- Policy、Executor、Trace 和 Runtime 可以互相协作；
- 未注册 Tool 会被拒绝；
- 高风险 Tool 会返回等待审批结果；
- 低风险测试 Tool 可以被执行；
- Tool 结果统一转换为 `ToolResult`；
- Harness 可以在一次 Tool 调用后再次接收决策；
- 达到最大循环次数时会停止；
- 关键运行过程可以从 `TraceRecorder` 读取；
- 没有真实模型调用，也没有连接外部业务系统。

## 后续连接关系

完成第三步后，下一步的连接方向是：

```text
第四步：CustomerServiceAgent 产生决策
        ↓
第五步：Memory 读取历史并保存结果
        ↓
第六步：ContextBuilder 组装模型上下文
        ↓
后续：真实 Tool、知识库、Router 和多 Agent
```

第三步的 Harness 是控制层，不是一个 Agent。Agent 负责理解问题和提出决策，Harness 负责判断和执行系统允许的动作。
