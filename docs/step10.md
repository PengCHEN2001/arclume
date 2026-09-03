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
│   ├── general_agent.py                    # 通用客服 Agent
│   ├── technical_agent.py                  # 技术支持 Agent
│   ├── billing_agent.py                    # 账单和退款 Agent
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
  → GeneralAgent / TechnicalAgent / BillingAgent
  → Context + Skill + RAG
  → Harness / Tool
  → 最终回复
```

本步的三个 Agent 不是三个完全独立的系统。它们共用同一套模型调用、Memory、
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

## 三个领域 Agent

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

三个领域 Agent 当前都继承 `CustomerServiceAgent`，因此不会复制三份 Memory、
Context 或模型调用代码。

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

`AgentType`：`general`、`technical`、`billing` 三种可执行 Agent。

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
_combine_responses()：合并复合问题的多个结果
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
| 明确要求转人工或紧急升级 | General | 无 | 否 | escalation |
| 无法判断的复杂问题 | General | 无 | 否 | 无，先请求澄清 |

转人工不是独立的第四个 LLM Agent，而是一次路由结果和 State 状态。真正的
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
7. 两个 Agent 按相同的 RAG 开关查询知识库
8. 各自经过 Harness 执行知识检索 Tool
9. ContextBuilder 将 State、实体、Skill、知识和历史组合给模型
10. Orchestrator 按主 Agent 在前的顺序合并回复
11. API 返回回复、意图、主 Agent、辅助 Agent 和路由原因
```

单一退款问题则不会并行：

```text
/chat
  → IntentRecognizer(refund)
  → Orchestrator
  → BillingAgent
  → refund Skill + RAG + Harness
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
```

三个 Agent 共享底层资源，但每个 Agent 有自己的系统指令和名称。

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
```

### `/health` 增加内容

```text
agents：当前三个 Agent
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
