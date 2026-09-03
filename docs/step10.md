# 第十步：建立意图识别、路由和多 Agent 协作

## 当前项目目录

```text
arclume/
├── api/
│   ├── __init__.py                         # Python 包声明
│   └── main.py                             # FastAPI 入口和应用资源初始化
├── agents/
│   ├── __init__.py                         # Python 包声明
│   ├── customer_service_agent.py           # 所有领域 Agent 共用的执行逻辑
│   ├── agent_profile.py                    # Agent 角色、流程、输入输出和 Tool 范围
│   ├── general_agent.py                    # 通用客服 Agent
│   ├── technical_agent.py                  # 技术支持 Agent
│   ├── billing_agent.py                    # 账单和退款 Agent
│   ├── escalation_agent.py                  # 人工升级和交接 Agent
│   ├── response_composer.py                 # 合并多个 Agent 的结果
│   └── agent_orchestrator.py                # 意图后的中央编排器
├── core/
│   ├── __init__.py                         # Python 包声明
│   ├── llm_utils.py                        # 大模型调用
│   ├── intent_recognizer.py                # 意图、实体和紧急程度识别
│   ├── context_builder.py                  # 组装一次模型请求的 Context
│   └── skill_loader.py                     # 读取静态 Skill
├── harness/                                # Tool 权限、执行和追踪边界
├── knowledge/                              # ChromaDB 知识库
├── memory/                                 # Redis 对话记忆和 AgentState
├── schemas/                                # API、State、Context、Tool 数据结构
├── skills/
│   ├── refund/SKILL.md                     # 退款处理规范
│   ├── logistics/SKILL.md                  # 物流处理规范
│   ├── escalation/SKILL.md                 # 转人工规范
│   └── technical/SKILL.md                  # 技术排障规范
├── tools/                                  # 当前业务 Tool 函数
├── data/demo_docs/                         # RAG 演示文档
└── docs/step10.md                          # 本步骤记录
```

## 本步目标

前面 `/chat` 还是直接进入一个客服 Agent。本步把请求先交给意图识别器，再由
中央编排器选择领域 Agent：

```text
用户消息
  → IntentRecognizer
  → AgentOrchestrator
  → AgentProfile
  → GeneralAgent / TechnicalAgent / BillingAgent / EscalationAgent
  → Context + Skill + RAG
  → Agent Tool Loop
  → Harness / Tool
  → ResponseComposer
  → 最终回复
```

本步的多个 Agent 不是多个完全独立的系统。它们共用同一套模型调用、Memory、
AgentState、ContextBuilder、知识库和 Harness，只通过不同的系统指令、Skill
和路由职责体现领域差异。

## 意图识别结果

`core/intent_recognizer.py` 负责在 Agent 执行前生成统一的分析结果：

```text
intent：细粒度意图，例如 refund、logistics、technical_login
intent_group：query、billing、technical、account 等大类
confidence：识别置信度
urgency：low、medium、high、critical
entities：订单号、物流单号、金额、错误码、日期
source_scores：pattern、embedding、llm 各自的得分
domain_scores：general、technical、billing 三个领域得分
matched_intents：复合问题中命中的多个意图
should_use_rag：本次是否应该查询知识库
```

当前支持的主要意图包括：

```text
order_status、logistics、refund、invoice、payment_issue
account_security、technical_login、technical_crash
greeting、feedback、complaint、human_handoff、other
```

## `core/intent_recognizer.py`

### 文件作用

在正式调用客服 Agent 之前，先判断“用户在处理什么问题”。这个模块只负责识
别，不负责选择 Agent，也不负责调用 RAG 或 Tool。

### 类和同层结构

`IntentCategory`：所有细粒度意图的枚举。

`UrgencyLevel`：请求紧急程度。

`IntentResult`：本次识别结果的数据结构。

`IntentRecognizer` 的核心属性：

```text
llm：可选的大模型客户端
use_llm：是否额外调用一次模型做意图细化，默认关闭
confidence_threshold：判断结果是否可靠的阈值
_cache：进程内意图结果缓存
```

核心方法：

```text
recognize()：返回 IntentResult
_pattern_scores()：统计关键词和模式命中
_embedding_match()：使用本地确定性 n-gram 相似度做轻量匹配
_llm_match()：可选的大模型 JSON 意图识别
_fuse()：合并多个识别来源
_extract_entities()：提取订单号、金额、错误码等实体
_detect_urgency()：判断紧急程度
_domain_scores()：转换为三个 Agent 领域的分数
clear_cache()：规则变化后清理缓存
```

当前默认先使用本地模式匹配和轻量相似度，不会因为每条消息增加一次模型调用。
如果之后希望使用模型理解复杂语义，可以设置：

```env
ARCLUME_INTENT_LLM_ENABLED=true
```

这样只有本地识别置信度不足时，才进行一次可选的模型细化。后续如果需要更完
整的三路融合，可以再接入正式的 Embedding 服务和评测权重。

## RAG 触发判断

意图识别结果会给出 `should_use_rag`：

```text
退款、账单、发票、物流、订单、账户、技术故障 → 使用 RAG
问候、满意反馈、明确转人工、无法识别         → 暂不使用 RAG
```

这样当前流程不再对每一条消息都查询知识库。知识库仍然使用第七步建立的基础
检索链路；查询改写、多路召回、去重和模型重排属于后续的 RAG 增强阶段，本步
先把“什么时候检索”接入正确的位置。

## 三个领域 Agent 和升级节点

### `agents/customer_service_agent.py`

这是共用执行基类，保留原来的对话处理流程：

```text
读取 Memory 和 AgentState
→ 按参数加载 Skill
→ 按路由决定是否查询知识库
→ ContextBuilder 组装 Context
→ LLMClient 生成回复
→ 保存消息和更新 State
```

本步新增的主要参数：

```text
knowledge_enabled：本次是否允许查询知识库
intent：识别出的细粒度意图
intent_group：意图大类
intent_confidence：意图置信度
urgency：紧急程度
entities：结构化实体
supporting_agents：辅助 Agent 列表
routing_reason：本次路由原因
persist：是否写入共享对话记录
```

`persist=False` 主要用于辅助 Agent。复合问题并行处理时，辅助 Agent 只生成
分析结果，不重复写入用户消息和模型回复，避免 Redis 中出现重复记录。

### `agents/general_agent.py`

职责：处理问候、一般咨询、订单和物流问题，也是专属 Agent 失败后的回退目标。

主要配置：

```text
name：general
system_prompt：通用客服规则
```

### `agents/technical_agent.py`

职责：处理登录失败、错误码、系统崩溃和配置问题。

主要配置：

```text
name：technical
system_prompt：技术排障规则
默认 Skill：technical
```

### `agents/billing_agent.py`

职责：处理退款、发票、账单、重复扣款和支付问题。

主要配置：

```text
name：billing
system_prompt：账单和退款规则
退款类请求使用 Skill：refund
```

### `agents/escalation_agent.py`

职责：处理明确转人工、高风险或紧急请求。

它不是普通的问答 Agent，不继续猜测业务结果，而是记录升级状态并生成安全的
交接说明。后续接入工单系统时，可以在这个节点连接人工队列或工单 Tool。

三个领域 Agent 和升级 Agent 当前都复用 `CustomerServiceAgent` 的资源接口，因
此不会复制三份 Memory、Context 或模型调用代码。升级 Agent 的回复逻辑目前是
确定性的，不额外消耗模型调用。

## AgentProfile

`agents/agent_profile.py` 为每个 Agent 保存结构化角色契约。它解决的问题是：
Agent 的区别不能只靠不同的 system prompt，还需要明确它负责什么、怎么处理、
能看到什么和什么时候升级。

核心字段：

```text
role：角色名称
mission：主要任务
workflow：处理步骤
input_contract：允许使用的输入信息
output_contract：回复必须包含的内容
handoff_conditions：需要转人工的条件
tool_scope：该 Agent 允许使用的 Tool 名称
model：可选的专属模型
temperature：模型随机性
max_tokens：单次回复上限
```

`AgentProfile` 会被写入模型提示词，同时用于筛选模型可见的 Tool。模型即使尝试
调用白名单之外的 Tool，Harness 也会再次拒绝，不能只依赖模型自觉遵守。

## Agent Tool Loop

当当前模型接口支持 OpenAI-compatible Tool Calling 时，领域 Agent 可以执行下面
的循环：

```text
Agent / Model 返回 Tool Call
  → 根据 AgentProfile 过滤 Tool
  → Harness 检查权限和风险
  → Harness 执行 Tool
  → ToolResult 返回模型
  → 模型生成最终回复或继续请求 Tool
```

`core/llm_utils.py` 新增 `chat_with_tools()`，只负责解析兼容格式的模型响应；它
不负责决定权限。真正的权限、参数检查、超时和重试仍然由 Harness 负责。

本步的 Tool Loop 有最大轮数限制，防止模型无限调用 Tool。没有配置模型、模型不
支持 Tool Calling，或测试使用 Fake LLM 时，仍然可以使用原来的普通文本调用路径。

## Tool Scope

当前各 Agent 的 Tool 范围如下：

| Agent | 允许的 Tool |
| --- | --- |
| General | `knowledge_search`、`order_query`、`logistics_query`、`suggest_required_fields` |
| Technical | `knowledge_search`、`lookup_error_code`、`build_diagnostic_plan` |
| Billing | `knowledge_search`、`check_billing_fields`、`compare_amounts` |
| Escalation | `create_handoff_summary` |

这里的 Tool 都是内部 Python Tool。第十一步才继续完善统一 Tool Manager、缓存、
熔断、Fallback 和增强 RAG，不在本步提前实现。

## ResponseComposer

`agents/response_composer.py` 负责把主 Agent 和辅助 Agent 的结果整理成一个回复：

```text
主 Agent 结果优先
  → 删除完全重复的结果
  → 保留不同的专业补充
  → 输出一条最终回复
```

当前使用确定性合并，不再额外调用模型，避免复合问题产生不必要的成本。后续如
果出现大量冲突答案，再评估是否增加专门的模型合并步骤。

## `agents/agent_orchestrator.py`

### 文件作用

这是多 Agent 的中央入口。它负责协调，而不是自己回答业务问题：

```text
识别意图
→ 计算领域分数
→ 选择主 Agent
→ 必要时选择辅助 Agent
→ 执行 Agent
→ 失败时回退
→ 返回结构化结果
```

### 类和同层结构

`AgentType`：`general`、`technical`、`billing` 和 `escalation` 四种 Agent 节点。

`AgentStats`：保存调用次数、成功次数、平均耗时和路由分数。现在是进程内统计，
后续由 Monitor 接管并持久化。

`AgentResponse`：一个 Agent 的内部执行结果。

`RoutingDecision`：保存主 Agent、辅助 Agent、路由原因、置信度和 RAG 开关。

`OrchestratorResult`：返回给 API 的最终编排结果。

`AgentOrchestrator` 的核心属性：

```text
intent_recognizer：意图识别器
confidence_threshold：低置信度判断阈值
_pool：按 AgentType 保存 Agent 实例
_stats：对应每个 Agent 的运行统计
```

核心方法：

```text
run()：一次请求的总入口
_make_decision()：生成 RoutingDecision
_run_parallel()：并行执行主 Agent和辅助 Agent
_execute()：执行一个 Agent 并更新统计
_best_agent()：按 routing_score 选择可用实例
_skills_for()：根据领域和意图选择 Skill
ResponseComposer.compose()：合并复合问题的多个结果
get_stats()：提供给健康检查和后续 Monitor
list_agents()：返回当前注册的 Agent
```

## 当前路由规则

| 用户问题 | 主 Agent | 辅助 Agent | RAG | Skill |
| --- | --- | --- | --- | --- |
| 问候、普通咨询 | General | 无 | 否 | 无 |
| 订单状态、物流 | General | 无 | 是 | logistics |
| 退款、发票、支付异常 | Billing | 无 | 是 | refund |
| 登录、崩溃、错误码 | Technical | 无 | 是 | technical |
| 同时包含技术和账单问题 | 得分较高者 | 另一个领域 Agent | 是 | 按领域分别加载 |
| 明确要求转人工或紧急升级 | Escalation | 无 | 否 | escalation |
| 无法判断的复杂问题 | General | 无 | 否 | 无，先请求澄清 |

Escalation 是独立的升级节点，但当前使用确定性回复，不额外调用模型。真正的
工单创建仍然必须经过高风险 Tool 和人工审批。

## 典型请求流程

以“登录报 401，而且还重复扣款了”为例：

```text
1. /chat 接收消息，并读取已有 Redis 历史
2. IntentRecognizer 识别出 technical_login 和 payment_issue
3. domain_scores 同时给 technical 和 billing 较高分
4. Orchestrator 选择一个主 Agent，另一个作为辅助 Agent
5. 两个 Agent 并行处理，主 Agent 持久化本轮对话
6. TechnicalAgent 加载 technical Skill，BillingAgent 加载 refund Skill
7. 每个 Agent 根据 AgentProfile 得到自己的 Tool Scope
8. 模型需要时发起 Tool Call，Harness 检查并执行
9. ToolResult 返回模型，模型继续处理或生成最终回答
10. ContextBuilder 将 State、实体、Skill、知识和历史组合给模型
11. ResponseComposer 按主 Agent 优先合并多个结果
12. API 返回回复、意图、主 Agent、辅助 Agent、路由原因和 Tool 记录
```

单一退款问题则不会并行：

```text
/chat
  → IntentRecognizer(refund)
  → Orchestrator
  → BillingAgent
  → AgentProfile + refund Skill + RAG + Harness Tool Loop
  → Redis 保存结果
  → ChatResponse
```

## API 变化

### 启动阶段

`api/main.py` 现在创建：

```text
LLMClient
ConversationMemory
StateStore
KnowledgeBase
SkillLoader
HarnessRuntime
GeneralAgent
TechnicalAgent
BillingAgent
IntentRecognizer
AgentOrchestrator
EscalationAgent（由 AgentOrchestrator 组装）
ResponseComposer（由 AgentOrchestrator 使用）
```

四个 Agent 节点共享底层资源，但每个 Agent 有自己的名称、Profile 和处理边界。

### `/chat` 返回字段

除原来的 `message`、`model`、`conversation_id` 外，现在还返回：

```text
intent：最终意图
intent_group：意图大类
primary_agent：主 Agent
supporting_agents：辅助 Agent 列表
routing_reason：路由原因和领域得分
routing_confidence：路由置信度
escalated：是否触发升级
request_id：本次请求的唯一标识
tools_used：本次请求成功使用的 Tool
tool_traces：本次请求的 Tool 调用记录
```

### `/health` 增加内容

```text
agents：当前四个 Agent 节点
intent_llm_enabled：是否开启意图模型细化
agent_stats：各 Agent 的调用和成功统计
```

## 本步完成的范围

```text
完成：细粒度 IntentCategory 和 IntentResult
完成：本地模式识别、轻量相似度和可选 LLM 细化
完成：实体、紧急程度、领域分数和 RAG 开关
完成：GeneralAgent、TechnicalAgent、BillingAgent
完成：中央 AgentOrchestrator
完成：主 Agent、辅助 Agent 和复合问题并行处理
完成：低置信度澄清和专属 Agent 失败回退
完成：按领域选择 Skill
完成：/chat 返回路由信息
完成：路由信息写入 AgentState 和 Context
完成：AgentProfile 结构化角色契约
完成：按 Profile 暴露和限制 Agent Tool
完成：OpenAI-compatible Tool Calling 的基础循环
完成：独立的 EscalationAgent
完成：ResponseComposer 和请求级 Tool 结果字段
```

## 仍然留到后续的增强

这些不是遗漏，而是建立在本步路由稳定之后继续加入：

```text
查询改写、多路 RAG 召回、去重、重排序和相似度阈值
正式 Embedding 服务和更完整的三路意图融合
多个同类型 Agent 实例和真正的性能路由
Monitor 写入动态 routing penalty
ChromaDB episodic memory 和 user profile memory
历史消息压缩和长期记忆更新
Tool 缓存、熔断、fallback 和持久化运行统计
完整评测、LLM Judge 和回归检测
Skill 热加载与旁路自进化
```

本步新增的编排升级已经完成；下一步只处理 RAG 和 Tool 治理，不重复设计
AgentProfile、Agent Tool Loop 或升级节点。

## 本地验证

本步不需要真实模型调用：

```bash
source .venv/bin/activate
python -m compileall api agents core harness knowledge memory schemas tools
```

可以使用 FastAPI 健康检查确认三个 Agent 已注册：

```bash
curl http://127.0.0.1:8000/health
```

在没有设置 `LLM_API_KEY` 时，`/health` 仍然可以返回；此时不要调用真实的
`/chat`，以免产生模型费用。当前的意图识别和编排逻辑可以通过 Fake LLM 的本
地模拟测试验证。
