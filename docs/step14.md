# 第十四步：完善 Dynamic Skills 和完整 Trace

## 当前项目目录

```text
arclume/
├── api/
│   └── main.py                          # API、Skill 管理接口和 Trace 查询接口
├── agents/
│   ├── customer_service_agent.py        # Skill 注入、RAG 和 Memory Trace
│   └── agent_orchestrator.py            # 意图、路由、Agent 和响应 Trace
├── core/
│   └── skill_loader.py                   # Skill metadata、筛选和热加载
├── harness/
│   ├── runtime.py                        # Tool Loop 和 Trace 关联
│   └── trace.py                          # 结构化请求 Trace
├── skills/
│   ├── refund/SKILL.md                  # Billing / refund Skill
│   ├── logistics/SKILL.md               # General / logistics Skill
│   ├── technical/SKILL.md               # Technical Skill
│   └── escalation/SKILL.md              # Human handoff Skill
├── tests/
│   ├── test_skills.py                   # Skill metadata、筛选和热加载测试
│   └── test_trace.py                    # Trace 记录和 Harness 关联测试
├── .env.example                         # Skill 和 Trace 配置模板
├── README.md                            # 当前项目能力说明
└── docs/step14.md                       # 本步骤记录
```

## 本步目标

第 13 步完成了 Hybrid RAG。本步继续沿着完整 Agent 运行链路补齐两块基础能力：

```text
Skill：让不同 Agent 只拿到适合自己的规则，并且可以人工修改后热加载
Trace：记录一次请求从进入系统到最终响应的完整执行过程
```

本步的 Skill 仍然是人工维护的 Markdown 文件。模型不能生成、修改、发布或回滚
Skill。所谓 Dynamic，指的是 metadata 筛选、文件变化检测和热加载，不是自动进化。

## Skill 的设计

### `skills/*/SKILL.md`

每个 Skill 文件增加统一的 front matter。当前主格式是 `SKILL.md`，Loader 同时兼容
独立的 `.md`、`.txt` 和 `.json` 文件：

```markdown
---
name: refund
description: Handle refunds, payment timing, and refund eligibility safely.
keywords: refund, reimbursement, payment, chargeback, repayment
agents: billing, general
enabled: true
---

# Refund Handling Skill
...
```

字段作用：

```text
name         # Skill 的稳定名称
description  # 供管理接口和人工查看的简短说明
keywords     # 自动匹配用户问题的关键词
agents       # 允许注入该 Skill 的 Agent 名称；为空表示所有 Agent
enabled      # 是否允许运行时使用
```

### `core/skill_loader.py`

作用：读取、解析、筛选并缓存人工维护的 Skill 文件。

核心数据结构：`SkillDocument`

```text
name
description
keywords
agents
enabled
content
path
```

核心方法：

```text
from_environment()                         # 从环境变量创建 Loader
list_available()                            # 列出已发现的 Skill 名称
list_skills()                               # 读取全部 Skill metadata
load(name)                                  # 按目录名、文件名或 metadata name 读取
load_many(names)                            # 按指定顺序读取多个 Skill
select_for_agent(agent, query, names)       # 按 Agent、enabled 和关键词筛选
render(documents)                            # 渲染 description、正文和总长度限制
prompt_for(message, agent, names)             # 选择并渲染 Skill prompt
reload()                                    # 清理缓存，让修改后的文件立即生效
```

筛选规则：

```text
显式 names 不为空
→ 作为人工指定的候选 allowlist
→ 仍然检查 enabled、agents 和 keywords
→ 保留指定顺序

显式 names 为空
→ 检查 enabled 和 Agent 范围
→ keywords 为空的 Skill 视为全局 Skill
→ 否则只注入命中关键词的 Skill
```

这样不会把所有 Skill 都放进每一次 Context，也不会让不相关的 Agent 看到其他领域
的处理规则。

### `agents/customer_service_agent.py`

Agent 不再直接调用 `load_many()` 拼接文件，而是调用 `select_for_agent()`。因此，
即使上层没有显式传入 Skill 名称，也可以使用当前 Agent 和用户问题做有限的关键词
匹配。

最终注入 Context 的内容由 Loader 统一渲染：

```text
[Skill name]
Description: skill description
skill content
```

文件路径、keywords、agents 和 enabled 状态不会直接作为模型规则注入，只用于管理和
筛选。单个 Skill 默认最多注入 3200 个字符，全部 Skill 默认最多注入 5000 个字符。

## Skill 管理接口

### `GET /skills`

返回 metadata，不返回完整 Skill 内容：

```text
GET /skills
→ root_dir
→ count
→ skills
  → name
  → description
  → keywords
  → agents
  → enabled
  → path
  → content_chars
→ errors
```

### `POST /skills/reload`

清空当前进程的 Skill cache。之后的请求会重新读取磁盘上的 Skill 文件。

通常的人工修改流程：

```text
人工修改 skills/refund/SKILL.md
→ POST /skills/reload
→ 下一次请求读取新的 Skill 内容
```

文件的 mtime 发生变化时，Loader 也会自动重新读取，不要求每一次都手动调用接口。

## Trace 的设计

### `harness/trace.py`

本步把原来主要记录 Harness Tool Loop 的 Trace，扩展为请求级 Trace。

`TraceEvent` 核心字段：

```text
event_id         # 事件唯一 ID
event_type       # 事件类型
timestamp        # UTC 时间
request_id       # 一次 API 请求的关联 ID
conversation_id  # 会话 ID
agent_name       # 相关 Agent
call_id          # 相关 Tool Call
tool_name        # 相关 Tool
data             # 该事件的结构化详情
```

当前事件类型：

```text
REQUEST_STARTED
INTENT_RECOGNIZED
ROUTE_SELECTED
SKILLS_SELECTED
RAG_COMPLETED
AGENT_STARTED
AGENT_COMPLETED
RUNTIME_STARTED
DECISION_RECEIVED
POLICY_EVALUATED
TOOL_EXECUTION_FINISHED
MEMORY_UPDATED
RESPONSE_COMPOSED
REQUEST_COMPLETED
REQUEST_FAILED
RUNTIME_STOPPED
RUNTIME_FAILED
```

### Trace 产生位置

```text
AgentOrchestrator
→ REQUEST_STARTED
→ INTENT_RECOGNIZED
→ ROUTE_SELECTED
→ AGENT_STARTED / AGENT_COMPLETED
→ RESPONSE_COMPOSED
→ REQUEST_COMPLETED

CustomerServiceAgent
→ SKILLS_SELECTED
→ RAG_COMPLETED
→ MEMORY_UPDATED

HarnessRuntime
→ RUNTIME_STARTED
→ DECISION_RECEIVED
→ POLICY_EVALUATED
→ TOOL_EXECUTION_FINISHED
→ RUNTIME_COMPLETED / RUNTIME_STOPPED / RUNTIME_FAILED
```

所有事件使用同一个 `request_id` 关联。多 Agent 并行执行时，多个 Agent 的事件会
出现在同一条请求 Trace 中，同时通过 `agent_name` 区分来源。

### Trace 的保存范围

本步只使用有上限的进程内存保存 Trace：

```text
ARCLUME_TRACE_MAX_EVENTS=10000
```

超过上限后删除最早事件。这样适合本地开发、调试和后续 Monitor 接入，不把临时
Trace 当作长期业务数据。未来需要多实例部署时，再接入日志系统、时序数据库或
专门的 Trace 存储。

### `GET /traces/{request_id}`

返回指定请求保留的全部事件：

```text
GET /traces/{request_id}
→ request_id
→ events[]
```

接口只返回结构化事件，不返回 Skill 完整内容，也不额外调用模型。

## 一次请求的当前流程

```text
POST /chat
→ REQUEST_STARTED
→ IntentRecognizer
→ INTENT_RECOGNIZED
→ ROUTE_SELECTED
→ 选择 Agent
→ SKILLS_SELECTED
→ RAG_COMPLETED
→ ContextBuilder
→ Agent / Harness / Tool Loop
→ MEMORY_UPDATED
→ RESPONSE_COMPOSED
→ REQUEST_COMPLETED
→ 返回 ChatResponse
```

## 本步暂不实现

```text
模型自动生成 Skill
模型自动修改 Skill
自动发布 Skill
自动回滚 Skill
把 Trace 写入 Redis 或外部观测平台
根据 Trace 自动修改路由权重
```

这些能力需要先有 Evaluation 和 Monitor 的可靠数据，不能在没有评测的情况下让
模型直接改变线上行为。

## 配置

```text
ARCLUME_SKILLS_DIR=./skills
ARCLUME_SKILLS_MAX_PROMPT_CHARS=5000
ARCLUME_TRACE_MAX_EVENTS=10000
```

## 本步完成标准

```text
Skill 文件拥有统一 metadata
Skill 可以按 enabled、Agent 和关键词筛选
Skill 修改后可以热加载
一次请求可以关联完整的主要执行事件
多 Agent 和 Tool 事件共享 request_id
可以通过接口查看 Skill metadata 和请求 Trace
Trace 有内存上限，不会无限增长
```

测试命令：

```bash
./.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```
