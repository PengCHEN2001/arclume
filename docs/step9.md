# 第九步：加入业务 Tools 和 Harness 执行治理

## 当前项目目录

```text
arclume/
├── api/
│   ├── __init__.py                 # Python 包声明
│   └── main.py                    # FastAPI 入口和资源初始化
├── agents/
│   ├── __init__.py                 # Python 包声明
│   └── customer_service_agent.py  # 单 Agent 客服逻辑
├── core/
│   ├── __init__.py                 # Python 包声明
│   ├── llm_utils.py               # 大模型 HTTP 调用
│   ├── context_builder.py         # 组装一次模型请求的 Context
│   └── skill_loader.py             # 读取静态 Skill 文件
├── harness/
│   ├── __init__.py                 # Python 包声明
│   ├── policy.py                  # Tool 权限和风险判断
│   ├── executor.py                # Tool 注册、执行和结果统一
│   ├── trace.py                   # Harness 事件记录
│   └── runtime.py                 # Harness 运行控制和最小循环
├── knowledge/
│   ├── __init__.py                # 知识库异常类型
│   └── knowledge_base.py          # ChromaDB 文档入库和检索
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
├── skills/
│   ├── refund/SKILL.md            # 退款处理规范
│   ├── logistics/SKILL.md         # 物流处理规范
│   └── escalation/SKILL.md        # 转人工规范
├── tools/
│   └── tool_functions.py          # 当前所有 Tool 函数和统一注册
├── data/
│   └── demo_docs/                 # RAG 演示知识文档
├── docs/
│   ├── step1.md                  # 第一步记录
│   ├── step2.md                  # 第二步记录
│   ├── step3.md                  # 第三步记录
│   ├── step4.md                  # 第四步记录
│   ├── step5.md                  # 第五步记录
│   ├── step6.md                  # 第六步记录
│   ├── step7.md                  # 第七步记录
│   ├── step8.md                  # 第八步记录
│   └── step9.md                  # 第九步记录
├── .env.example                  # 环境变量模板
├── .gitignore                    # Git 忽略规则
├── .dockerignore                 # Docker 构建忽略规则
├── Dockerfile                    # 应用镜像描述，暂不测试
├── docker-compose.yml             # API、Redis 和 ChromaDB 服务编排
├── requirements.txt              # Python 依赖
└── README.md                     # 项目说明
```

## 本步目标

前面已经建立了 Harness 的 Policy、Executor、Trace 和 Runtime，也已经定义
了 `ToolCall` 与 `ToolResult`。本步把几个最小业务 Tool 注册进去，并让当前
的知识检索通过 Harness 边界执行。

本步不连接真实订单系统、物流系统或工单系统。先用确定性的模拟函数验证：

```text
Tool 函数
  → ToolDefinition
  → ToolExecutor 注册
  → HarnessRuntime
  → Policy 判断
  → Executor 执行或暂停
  → ToolResult
```

## 本步新增和修改的文件

```text
tools/tool_functions.py              # 新增：所有当前 Tool 函数和注册函数
agents/customer_service_agent.py     # 修改：知识检索可通过 Harness 执行
api/main.py                           # 修改：创建 Harness 并注册 Tools
Dockerfile                            # 修改：复制 tools 目录
README.md                             # 修改：更新第九步状态
docs/step9.md                         # 新增：本步骤设计和测试记录
```

本步没有创建 `mcp/tool_manager.py`，也没有为每一个简单函数创建一个文件。
`harness/executor.py` 已经是当前项目统一的 Tool 注册和执行中心。

## Tool 的最小结构

当前每个业务 Tool 主要就是一个函数：

```text
arguments：模型或上层 Agent 提供的参数
context：运行时注入的服务依赖和上下文
return：业务结果，之后由 Executor 统一转换成 ToolResult
```

`tools/tool_functions.py` 中当前有：

```text
knowledge_search(arguments, context)   # 调用 KnowledgeBase
order_query(arguments, context)        # 返回模拟订单信息
logistics_query(arguments, context)    # 返回模拟物流信息
ticket_create(arguments, context)      # 返回模拟工单结果
register_tools(executor)               # 注册以上四个函数
```

这里没有为每个 Tool 创建一个类。`ToolDefinition` 只是为函数补充运行配置：

```text
name：Tool 名称
description：Tool 描述
handler：实际函数
input_schema：参数格式
risk_level：风险等级
timeout_seconds：超时时间
max_retries：失败后的额外尝试次数
allowed_agents：允许使用的 Agent
enabled：是否启用
```

## 当前四个 Tool

### `knowledge_search`

```text
风险：LOW
参数：query、top_k
实际逻辑：调用 knowledge/knowledge_base.py
```

它只是一个薄薄的 Tool 包装，不重复实现 ChromaDB 检索。当前 `/chat` 使用
它来获取 RAG 结果；独立的 `/knowledge/search` 测试接口仍然可以直接查询
KnowledgeBase。

### `order_query`

```text
风险：LOW
参数：order_id
返回：固定的模拟订单状态
```

当前不会连接数据库或订单 API。它只用于先验证参数校验、Tool 查找和结果返
回流程。

### `logistics_query`

```text
风险：LOW
参数：tracking_id
返回：固定的模拟物流状态
```

以后接入承运商或企业物流 API 时，主要替换函数内部的数据来源，外层
`ToolDefinition` 和 Harness 边界可以保留。

### `ticket_create`

```text
风险：HIGH
参数：customer_id、summary
返回：模拟工单结果
```

由于当前 Policy 默认要求 HIGH 风险 Tool 经过人工审批，正常通过
`HarnessRuntime.handle_tool_call()` 调用时，会先返回：

```text
requires_approval = true
```

不会直接执行工单函数。审批 API 和恢复执行流程留到后面设计。

## Tool 管理关系

```text
tools/tool_functions.py
  ├─ 定义 knowledge_search()
  ├─ 定义 order_query()
  ├─ 定义 logistics_query()
  ├─ 定义 ticket_create()
  └─ register_tools()
          ↓
harness/executor.py
  └─ ToolExecutor._tools
          ↓
harness/policy.py
  └─ 判断是否允许
          ↓
harness/runtime.py
  └─ 记录过程并返回 ToolResult
```

应用启动时的注册过程：

```text
ToolExecutor()
  → register_tools(executor)
  → HarnessRuntime(executor=executor)
  → CustomerServiceAgent(harness=harness)
```

这样 Tool 函数集中放在一个文件，Tool 的执行治理仍然集中在 Harness。

## 当前知识检索如何经过 Harness

当前 API 中，客服 Agent 查询知识库时会创建一个内部 `ToolCall`：

```text
CustomerServiceAgent
  → ToolCall(tool_name="knowledge_search")
  → HarnessRuntime.handle_tool_call()
  → ToolPolicy.evaluate()
  → ToolExecutor.execute()
  → knowledge_search()
  → KnowledgeBase.search_async()
  → ToolResult
  → knowledge_results
  → ContextBuilder
```

知识检索属于 LOW 风险，所以 Policy 会直接允许执行。这个过程只增加少量
Python 函数调用，不会增加一次大模型请求。

如果没有传入 Harness 的 Agent 进行单元测试，仍然允许直接调用
`KnowledgeBase.search_async()`，这样测试更简单。

## 一次请求的运行流程

当前 `/chat` 的主要流程：

```text
1. API 接收用户消息
2. Agent 从 Redis 读取 Memory 和 AgentState
3. Agent 创建 knowledge_search ToolCall
4. Harness 检查 Tool 是否存在、启用、允许当前 Agent 使用
5. Harness 执行知识检索
6. 检索结果进入 Context
7. LLMClient 调用模型
8. Agent 保存回复和更新 AgentState
9. API 返回 ChatResponse
```

如果未来模型主动请求 `order_query`：

```text
模型提出 ToolCall
  → Harness Policy
  → 允许
  → order_query()
  → ToolResult 回到 Agent Loop
```

如果未来模型请求 `ticket_create`：

```text
模型提出 ToolCall
  → Harness Policy
  → HIGH 风险
  → requires_approval=true
  → 暂停等待人工审批
```

## 本步暂时没有实现的内容

```text
真实订单数据库或订单 API
真实物流 API
真实工单系统
模型自动生成 ToolCall 的解析
审批接口和审批恢复
Tool 的持久化统计
多 Agent 权限配置
```

当前先验证 Harness 能否正确接收、检查、执行和返回 Tool。真实业务系统接入
后，需要再设计认证、幂等、审计字段和敏感数据处理。

## 测试方式

不需要调用真实模型 API，也不需要连接真实业务系统。

先做静态检查：

```bash
source .venv/bin/activate
python -m compileall api agents core harness knowledge memory schemas tools
```

再用终端命令分别测试低风险 Tool 和高风险审批：

```bash
python -c "import asyncio; from harness.runtime import HarnessRuntime; from tools.tool_functions import register_tools; from harness.executor import ToolExecutor; from schemas.tool import ToolCall; runtime=HarnessRuntime(executor=register_tools(ToolExecutor())); call=ToolCall(call_id='order-1', tool_name='order_query', arguments={'order_id':'ORD-1001'}, requested_by='customer_service'); print(asyncio.run(runtime.handle_tool_call(call)).model_dump())"
python -c "import asyncio; from harness.runtime import HarnessRuntime; from tools.tool_functions import register_tools; from harness.executor import ToolExecutor; from schemas.tool import ToolCall; runtime=HarnessRuntime(executor=register_tools(ToolExecutor())); call=ToolCall(call_id='ticket-1', tool_name='ticket_create', arguments={'customer_id':'CUS-1','summary':'Delivery issue'}, requested_by='customer_service'); print(asyncio.run(runtime.handle_tool_call(call)).model_dump())"
```

实际学习测试时，也可以写一个临时的小脚本，依次构造 `order_query` 和
`ticket_create` 的 `ToolCall`，然后检查：

```text
order_query → success=true
ticket_create → requires_approval=true
```

也可以检查 API 是否列出已注册 Tool：

```bash
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/health
```

返回结果中应该包含：

```json
{
  "tools": [
    "knowledge_search",
    "order_query",
    "logistics_query",
    "ticket_create"
  ]
}
```

## 本步完成标准

```text
完成：四个简单 Tool 函数集中在一个文件
完成：ToolDefinition 统一描述 Tool 配置
完成：ToolExecutor 统一注册和执行
完成：低风险知识检索经过 Harness
完成：高风险工单 Tool 会暂停等待审批
完成：订单和物流 Tool 可以用模拟数据测试
完成：没有调用真实模型和真实业务系统
暂不完成：真实业务连接、模型 Tool Call 解析和审批恢复
```
