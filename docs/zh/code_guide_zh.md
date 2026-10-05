# Arclume 代码结构与实现指南

本文介绍 Arclume 后端的目录结构、主要文件与类、模块之间的调用关系，以及修改某种行为时可以从哪里开始查。推荐先看第 1 章建立代码地图，再按第 2 章理解各层实现；需要运行项目、验证改动时查后面的章节。项目为什么这样设计、一次请求的完整故事见 `项目设计与全链路.md`。

本文按当前工作区代码编写。涉及外部模型、Redis、ChromaDB 的行为，必须在实际环境中再验证；不能因为单元测试通过就宣称真实服务可用。当前项目主要处理英文客服消息与英文知识文档。

## 1. 仓库地图：目录、文件和联动

先把仓库想成几个分工明确的部分：`api/` 接收请求，`core/` 判断并准备模型输入，`agents/` 决定由谁处理并生成回复；`memory/` 和 `knowledge/` 提供不同来源的数据；`tools/` 定义能力，`harness/` 控制能力的使用；`schemas/` 规定层与层之间传递的数据；`monitor/` 与 `evaluation/` 分别负责运行观测和离线评测。第 2 章再讲这些模块内部为什么这样写。

### 1.1 整体目录

```text
arclume/
├── api/                 HTTP 路由、启动和资源装配
├── agents/              路由、各角色 Agent、回答合并
├── core/                意图识别、模型客户端、Context/Skill 装配
├── schemas/             API、State、Context、Tool 的数据契约
├── memory/              Redis 工作记忆与 ChromaDB 长期记忆
├── knowledge/           知识文档切片、向量与 BM25 检索
├── tools/               实际工具函数、注册与检索管理
├── harness/             工具权限、执行、审批判断与 Trace
├── skills/              人工维护的场景指令文件
├── monitor/             运行指标、告警和有限的路由降权
├── frontend/            Vue/Vite Web 对话界面（可选）
├── evaluation/          用例、指标、报告和质量回归
├── tests/               不依赖真实外部服务的模块测试
├── data/demo_docs/      演示用英文知识文档
├── docs/                学习、设计、代码与评测文档
├── config/              Nginx 与 Prometheus 配置
├── requirements.txt     Python 依赖
├── docker-compose.yml   本地服务组合
└── Dockerfile           API 容器构建
```

这里的 `__init__.py` 多数用于声明包或导出异常，不是阅读主链路的重点；`memory/__init__.py`、`knowledge/__init__.py` 还定义了各自的错误类型。本文只介绍 `api/main.py` 使用的当前实现，不把计划中的 LangChain/LangGraph 对照版本算进主链路。

### 1.2 按目录展开：关键文件分别做什么

下面这棵树把运行、阅读或修改时最常会打开的文件展开到文件级。没有列出大多数 `__init__.py`、前端锁文件、缓存目录和生成的运行数据；它们通常不是理解主链路的入口。

```text
api/
└── main.py                    创建共享组件、定义 /chat 与各类管理接口

agents/
├── agent_orchestrator.py      根据 IntentResult 路由、并行执行、合并并写回最终回复
├── agent_profile.py           定义每类 Agent 的职责、流程、边界和工具范围
├── customer_service_agent.py  General/Technical/Billing 共用的执行器：建 Context、调模型和工具
├── general_agent.py           通用、产品、订单与物流类 Agent 的角色配置
├── technical_agent.py         技术故障类 Agent 的角色配置
├── billing_agent.py           退款、发票、支付类 Agent 的角色配置
├── escalation_agent.py        人工升级时的确定性处理与提示
└── response_composer.py       不再调模型，按主 Agent 优先顺序拼接多 Agent 回复

core/
├── intent_recognizer.py       关键词、模板、可选 LLM 复核、实体和子任务识别
├── context_builder.py         将历史、知识、Skill、状态和工具结果整理为模型消息
├── skill_loader.py            读取 SKILL.md，按 Agent/意图选择并渲染业务指令
└── llm_utils.py               OpenAI 兼容模型客户端、普通回答与 Tool Call 解析

schemas/
├── api.py                     ChatRequest、ChatResponse 等 HTTP 数据模型
├── state.py                   AgentState 与处理状态枚举
├── context.py                 单次模型调用所需的 Context 数据结构
└── tool.py                    ToolCall、ToolResult 等工具调用数据契约

memory/
├── conversation_memory.py     Redis 近期消息、会话摘要、压缩与最终消息写回
├── long_term_memory.py        ChromaDB 历史摘要和用户画像的读写
└── state_store.py             Redis 中 AgentState 的按用户/会话存取

knowledge/
├── knowledge_base.py          英文文档导入、按段落切片、ChromaDB Dense 检索
├── bm25_index.py              进程内 BM25 关键词索引
└── hybrid_retriever.py        Dense/BM25 并行检索、RRF 融合、去重和降级

tools/
├── tool_functions.py          knowledge_search、订单/物流 Mock 等具体工具函数与注册信息
└── tool_manager.py            工具执行增强层：查询改写、缓存、熔断、排序和降级

harness/
├── policy.py                  按工具、Agent、启用状态和风险级别决定允许/拒绝/需审批
├── executor.py                校验参数、处理超时与重试，并标准化 ToolResult
├── runtime.py                 串联 Policy、Executor、ToolManager 与 Trace 的统一入口
└── trace.py                   定义 Trace 事件，并按 request_id 保存进程内记录

monitor/
└── performance_monitor.py     汇总 Agent/Tool 成功率、延迟、告警与 Prometheus 指标

evaluation/
├── __main__.py                `python -m evaluation` 的命令行入口
├── models.py                  评测用例和评测报告的数据结构
├── runner.py                  运行意图/路由等本地评测
├── metrics.py                 Accuracy、Macro-F1、检索等指标计算
├── evaluator.py               通过 API 运行端到端评测
├── judge.py                   可选 LLM-as-a-Judge 的回答评分逻辑
├── regression.py              新旧报告的回归比较
└── data/                      冒烟、500 条合成意图/路由、演示 RAG 用例数据

skills/
├── refund/SKILL.md            退款/支付场景的业务处理说明
├── technical/SKILL.md         技术故障排查说明
├── logistics/SKILL.md         物流场景的业务处理说明
└── escalation/SKILL.md        人工升级时的处理说明

frontend/
├── src/App.vue                聊天页面、健康状态和基础 Trace 展示
├── src/api.js                 对后端 HTTP 接口的前端请求封装
├── src/main.js                Vue 应用启动入口
├── src/style.css              页面样式
├── package.json               前端依赖与 npm 脚本
└── vite.config.js             Vite 本地开发与构建配置

data/demo_docs/                可导入的英文演示知识文档
tests/                         单元/集成测试；按测试文件找到对应模块的预期行为
config/prometheus.yml          Prometheus 抓取 API 指标的配置
config/nginx/nginx.conf        Nginx 反向代理示例配置
docs/                          `zh/`、`eng/`、`fr/` 三种语言的项目文档；不在此逐文件展开
```

阅读代码时，可先从 `api/main.py` 进入；看到某一层的对象后，再按上面同名目录找到实现。比如想改“意图怎么识别”，直接看 `core/intent_recognizer.py`，随后查看 `tests/` 中对应测试和 `evaluation/` 的回归数据；不要先从 Agent Prompt 改起。

### 1.3 各文件具体放了什么

下面列的是理解主链路时值得先认识的文件和重要符号。它是**导航索引**，不是把每个私有辅助函数抄成一份随时会过期的源码副本。

#### 1.3.1 `api/` 与 `schemas/`：外部边界和共享数据类型

| 文件 | 里面是什么 | 通常什么时候打开 |
|---|---|---|
| `api/main.py` | `lifespan()` 装配共享组件；`chat()` 处理 `/chat`；`health()`、知识库、Skill、Trace、Monitor、评测等路由也在这里 | 新增接口、检查启动依赖、追 HTTP 到 Orchestrator 的调用 |
| `schemas/api.py` | `ChatRequest`/`ChatResponse` 和知识入库、评测的 Pydantic 请求模型 | 改请求/响应字段、理解对外数据约束 |
| `schemas/state.py` | `AgentStatus` 枚举与 `AgentState`：意图、实体、活跃 Agent、升级状态、版本等 | 改跨请求的案件处理状态 |
| `schemas/context.py` | `ContextMessage`、本轮模型材料 `Context`；包含历史、摘要、知识、Skill、Tool 结果及元数据 | 查模型本轮实际可以拿到哪些结构化内容 |
| `schemas/tool.py` | `ToolCall`（工具名、参数、发起方）与 `ToolResult`（成功、错误、审批、缓存、降级等） | 改 Tool 契约或 Trace 字段时 |

`ChatRequest` 和 `ChatResponse` 是 HTTP 契约；`AgentState` 是可保存的案件状态；`Context` 是一次请求的临时模型材料；`ToolCall/ToolResult` 是工具执行契约。名字都带“状态/结果”，但生命周期完全不同。具体字段始终以这些 Pydantic 定义为准。

#### 1.3.2 `core/`：理解请求、准备模型调用

| 文件 | 主要类/函数 | 负责什么 |
|---|---|---|
| `core/intent_recognizer.py` | `IntentCategory`、`IntentSubtask`、`IntentResult`、`IntentRecognizer.recognize()`；`_pattern_evidence()`、`_template_match()`、`_ambiguity_reasons()`、`_build_subtasks()`、`_information_need()`、`_planned_tool()` | 从消息与历史得到业务主题、疑点、实体、复合请求的领域子任务、证据需求和可选工具计划；不执行 Agent 或 Tool |
| `core/llm_utils.py` | `LLMSettings`、`LLMClient.chat()`、`chat_with_tools()`、`LLMToolResponse` | 统一读取供应商配置并调用 OpenAI 兼容 Chat Completions；解析普通文本、Tool Call，以及需要在下一轮原样回传的供应商扩展字段 |
| `core/context_builder.py` | `ContextBuilder.build()`、`render_system_prompt()`、`render_history()` | 将已经拿到的 Memory、知识、Skill、状态整理为模型消息；不主动访问数据库 |
| `core/skill_loader.py` | `SkillDocument`、`SkillLoader.select_for_agent()`、`render()`、`reload()` | 解析人工维护的 Skill；对意图已选中的候选只检查启用状态和 Agent 范围，对直接调用时才可按消息关键词发现 Skill；渲染规则文本 |

识别结果的核心字段可按四组读：`intent`、`intent_group`、`confidence` 回答“主要是什么问题”；`topic_evidence`、`ambiguity_reasons`、`supporting_domains` 解释“凭什么这样判断、是否还有独立主题”；`subtasks` 绑定“哪个 Agent 处理原句中的哪一部分”；`information_need`、`should_use_rag`、`planned_tool_name` 回答整条请求“回答前需要什么证据”。多 Agent 执行时还应看每个 `IntentSubtask` 自己的证据需求，不能只看请求级字段。

#### 1.3.3 `agents/`：谁处理，以及如何回答

| 文件 | 主要类/函数 | 负责什么 |
|---|---|---|
| `agents/agent_orchestrator.py` | `AgentType`、`RoutingDecision`、`AgentResponse`、`OrchestratorResult`、`AgentOrchestrator.run()`、`_make_decision()`、`_run_parallel()`、`_persist_final_turn()` | 路由、请求用户补充信息、多 Agent 并行、回退、合并结果、升级判断、最终对话写回 |
| `agents/agent_profile.py` | `AgentProfile` | 定义角色任务、工作步骤、输入/输出要求、转人工条件及 `tool_scope` |
| `agents/customer_service_agent.py` | `CustomerServiceAgent.respond()`、`_tool_schemas()`、`_run_tool_loop()`、`_record_tool_result()` | 普通领域 Agent 共享执行器：预取证据、挑 Skill、建 Context、调用模型和 Harness、更新 AgentState |
| `agents/general_agent.py` | `GeneralAgent` | 通用问题、订单/物流以及兜底；重点是它的 Profile、Tool 范围与系统提示 |
| `agents/technical_agent.py` | `TechnicalAgent` | 技术和登录故障；复用共享执行器，不复制整套 Tool Loop |
| `agents/billing_agent.py` | `BillingAgent` | 退款、发票、支付类问题；同样通过 Profile 与提示限定边界 |
| `agents/escalation_agent.py` | `EscalationAgent.respond()` | 确定性人工升级回复与状态；不调用普通领域 Agent 的模型回答流程 |
| `agents/response_composer.py` | `ResponseComposer.compose()` | 把主/辅 Agent 的成功回复按主回复优先的顺序合并；不再调用模型 |

`AgentOrchestrator.run()` 是编排入口，`CustomerServiceAgent.respond()` 是单个普通 Agent 的执行入口。`AgentResponse` 是一个 Agent 的内部结果；`OrchestratorResult` 是编排完成后交给 HTTP 层的内部结果；它们不是 `ChatResponse`。要找某个字段为什么出现在 API 里，通常要顺着这三个结果结构追。

#### 1.3.4 `memory/` 与 `knowledge/`：两类不同的数据来源

| 文件 | 主要类/函数 | 负责什么 |
|---|---|---|
| `memory/conversation_memory.py` | `ConversationMemory.get_context()`、`add_message()`、`_maybe_compact()`、`update_profile()` | Redis 的近期消息/摘要；必要时向长期记忆读取相关历史与画像 |
| `memory/state_store.py` | `StateStore.get_or_create()`、`save()` | Redis 中的结构化 `AgentState`，按用户与会话隔离 |
| `memory/long_term_memory.py` | `LongTermMemory.search_episodic()`、`add_episodic_summary()`、`get_user_profile()`、`update_user_profile()` | ChromaDB 中的历史摘要与用户画像，不存业务知识 chunk |
| `knowledge/knowledge_base.py` | `KnowledgeBase.add_documents()`、`search()`、`_chunk_text()`、`_chunk_id()` | 英文业务文档切片、ChromaDB 知识 collection、Dense 搜索 |
| `knowledge/bm25_index.py` | `BM25Index.replace()`、`upsert()`、`search()` | 进程内关键词索引与 BM25 打分 |
| `knowledge/hybrid_retriever.py` | `HybridRetriever.search_async()`、`refresh_async()`、`_rrf_fuse()` | 从 Dense/BM25 两路取候选，融合、去重并在分支故障时尽量降级 |

ChromaDB 同时被 `LongTermMemory` 和 `KnowledgeBase` 使用，但它们使用不同 collection：前者是用户历史与画像，后者是客服业务资料。不要因为都“用 ChromaDB”就把用户记忆当成 RAG 政策文档。

#### 1.3.5 `tools/` 与 `harness/`：能力和治理分开

| 文件 | 主要类/函数 | 负责什么 |
|---|---|---|
| `tools/tool_functions.py` | `knowledge_search()`、`order_query()`、`logistics_query()`、`lookup_error_code()`、`register_tools()` 等 | 具体 Tool 的行为与注册；订单/物流为演示数据，`ticket_create` 不是已打通的真实工单 |
| `tools/tool_manager.py` | `ToolManager.execute()`、`search_with_rewrite()`、`rewrite_query()`、`rerank()` | Tool 缓存/熔断/统计/降级；RAG 查询变体、结果去重和最终排序 |
| `harness/policy.py` | `ToolPolicy.evaluate()`、`PolicyAction`、`ToolRiskLevel` | 判定某次 ToolCall 允许、拒绝或需要审批；不执行 Tool |
| `harness/executor.py` | `ToolDefinition`、`ToolExecutor.execute()`、`_validate_arguments()` | 描述工具输入与风险配置，校验参数，处理超时/重试并规范化结果 |
| `harness/runtime.py` | `HarnessRuntime.handle_tool_call()`、`tool_schemas()`、`tool_trace()` | 把 Policy、Executor/ToolManager、Agent 范围与 Trace 串成一次受控调用 |
| `harness/trace.py` | `TraceEventType`、`TraceEvent`、`TraceRecorder` | 保留有容量上限的进程内请求事件，可按 `request_id` 查 |

`tools/` 回答“这个能力具体做什么”；`harness/` 回答“这次能否调用、怎样执行和留下证据”。`ToolManager` 实际继承 `ToolExecutor`，所以它既参与工具执行，也承载检索链路；这就是 `api/main.py` 会先注册 `ToolManager`，再把它交给 `HarnessRuntime` 的原因。

#### 1.3.6 运行、评测与资料文件

| 目录/文件 | 里面是什么 | 与主链路的关系 |
|---|---|---|
| `skills/*/SKILL.md` | refund、technical、logistics、escalation 的人工维护场景规则 | `/chat` 先按细粒度意图选择候选，再由 `SkillLoader` 检查启用状态和 Agent 范围后注入；不是 Python 可执行代码 |
| `monitor/performance_monitor.py` | `PerformanceMonitor`、告警/异常检测、指标输出与有限路由降权 | 后台定期读 Agent/Tool 统计；不替代离线质量评测 |
| `evaluation/__main__.py` | `python -m evaluation` 的 CLI 入口 | 本地意图/确定性路由评测，不启动完整聊天 |
| `evaluation/models.py`、`metrics.py`、`runner.py` | 用例/报告模型、分类和检索指标、用例执行 | 构成可重复的本地评测基础 |
| `evaluation/evaluator.py`、`judge.py`、`regression.py` | API 端到端评测、可选 LLM Judge、报告对比 | 需要分清真实模型调用与占位/失败结果 |
| `evaluation/data/` | `cases.json` 冒烟集、`intent_cases_500.json` LLM 生成的合成分类集、`rag_cases.json` 演示检索集 | 更改识别或切片后应复核数据和标签 |
| `tests/` | 每个核心模块的行为测试，主要使用替身 | 改动代码时用于回归；不能替代真实依赖测试 |
| `data/demo_docs/` | 退款、物流、安全、技术的英文演示文档 | 可以用来建立小型知识库，但不是正式业务政策 |
| `frontend/src/App.vue`、`api.js`、`main.js`、`style.css` | `App.vue` 组织聊天界面和基本状态展示；`api.js` 封装对后端 `/chat`、`/health`、`/monitor` 等请求；`main.js` 启动 Vue；`style.css` 定义页面样式 | 可选的本地演示界面，不参与后端业务判断。当前前端只展示 Monitor 是否活跃；完整指标仍应通过 `/monitor`、`/metrics` 或 Prometheus 查看 |
| `frontend/package.json`、`vite.config.js`、`index.html` | 前端依赖、Vite 开发/构建配置与页面入口 | 修改前端启动命令、代理或构建方式时查看 |
| `docs/zh/`、`docs/eng/`、`docs/fr/` | `zh/` 是当前最完整的中文学习与设计文档；`eng/` 和 `fr/` 放面向展示的英文、法文版本 | 文档不参与运行。项目总体说明、设计链路、代码导航、评测协议、PRD 和路线图应在三种语言版本之间保持对应关系 |
| `config/`、`Dockerfile`、`docker-compose.yml` | Nginx、Prometheus、容器运行与本地基础设施 | 改端口、密码、环境变量或部署时检查 |

### 1.4 从一次 `/chat` 找到具体文件

下面是**代码阅读顺序**，不是每条请求必经的运行步骤。想知道某个行为在哪一层发生，可先沿着这一列找：

| 关注点 | 主要位置 | 入口或关键方法 | 层的责任 |
|---|---|---|---|
| 请求校验、依赖创建、对外响应 | `schemas/api.py`、`api/main.py` | `ChatRequest`、`ChatResponse`、`lifespan()`、`chat()` | HTTP 契约及组装，不在这里写意图规则 |
| 主题、实体和证据需求 | `core/intent_recognizer.py` | `IntentRecognizer.recognize()` | 产出 `IntentResult`，不执行工具 |
| 路由、多 Agent、最终写回 | `agents/agent_orchestrator.py` | `run()`、`_make_decision()`、`_persist_final_turn()` | 决定由谁处理，组织最终对外结果 |
| 单个 Agent 的实际执行 | `agents/customer_service_agent.py` | `respond()`、`_run_tool_loop()` | 预取证据、组装上下文、调用模型/工具、维护 AgentState |
| 角色、Skill、模型上下文 | `agents/agent_profile.py`、`core/skill_loader.py`、`core/context_builder.py` | `AgentProfile`、`select_for_agent()`、`build()`、`render_history()` | 限定职责并整理模型可见材料 |
| 知识入库与检索 | `knowledge/`、`tools/tool_manager.py` | `add_documents()`、`search_with_rewrite()` | 切片、Dense/BM25、融合、去重、重排 |
| 工具审批和执行 | `harness/`、`tools/tool_functions.py` | `handle_tool_call()`、`evaluate()`、`execute()` | 权限/风险、参数、运行和 Trace |
| 会话、长期记忆和状态 | `memory/`、`schemas/state.py` | `get_context()`、`add_message()`、`get_or_create()` | 保存/读取跨请求数据 |

几个容易混淆的边界：`IntentResult.should_use_rag` 表示**计划需要知识**，不等于已经检索成功；`RoutingDecision` 是内部路由决定，不是 API 响应；`Context` 是本轮模型输入材料，不是持久记忆；`ToolResult` 表示工具尝试的结果，不能用 `tools_used` 代替完整的工具失败记录。

### 1.5 关键数据在层间怎样传递

```text
ChatRequest
  → api.chat() 读取 Memory，得到 history + memory_context
  → IntentRecognizer.recognize() 产出 IntentResult
      → 复合请求额外产出领域级 IntentSubtask
  → AgentOrchestrator._make_decision() 产出 RoutingDecision
  → Orchestrator 把各子问题交给对应 CustomerServiceAgent.respond()
  → 每个 Agent 按自己的子问题检索、生成回复和工具记录
  → ResponseComposer（仅多 Agent）形成最终文本
  → OrchestratorResult
  → api.chat() 转为 ChatResponse
```

`request_id` 标识**一次请求**，用于 Trace；`conversation_id` 标识**一段多轮会话**，用于 Memory。客户端省略 `conversation_id` 时，API 会生成一个并在响应中返回；后续要继续同一段会话，就必须复用它。`user_id` 用于隔离用户数据，未提供时是演示用默认值；真实业务不能依赖匿名默认值做租户隔离。

定位代码时最常遇到的几个对象及其字段位置：

| 对象（定义文件） | 优先看的字段 | 谁创建，谁使用 |
|---|---|---|
| `ChatRequest`（`schemas/api.py`） | `message`、`user_id`、`conversation_id` | 客户端传给 FastAPI；`api.chat()` 读取 |
| `IntentResult`（`core/intent_recognizer.py`） | `intent`、`entities`、`confidence`、`information_need`、`should_use_rag`、`planned_tool_name`、`supporting_domains`、`subtasks` | Recognizer 创建；Orchestrator 用于路由并传给 Agent |
| `IntentSubtask`（`core/intent_recognizer.py`） | `domain`、`query`、`intent`、`information_need`、`should_use_rag`、`planned_tool_name`、`entities` | Recognizer 为复合请求创建；Orchestrator 按领域找到任务并只把对应 `query` 交给 Agent |
| `RoutingDecision`（`agents/agent_orchestrator.py`） | `primary_agent`、`supporting_agents`、`use_rag`、`reason` | `_make_decision()` 创建；`run()` 决定执行路径 |
| `AgentState`（`schemas/state.py`） | `status`、`active_agent`、`needs_rag`、`needs_human`、`pending_approval`、`version` | Agent 读取/更新；`StateStore` 保存；字段存在不代表审批恢复流程已实现 |
| `Context`（`schemas/context.py`） | `conversation_history`、`memory_summary`、`knowledge_results`、`skill_instructions`、`metadata` | `ContextBuilder.build()` 创建；Agent 渲染给模型，不整对象保存 |
| `ToolCall` / `ToolResult`（`schemas/tool.py`） | `tool_name`、`arguments` / `success`、`data`、`error`、`requires_approval` | Agent/Harness 发起请求；Harness/Executor 返回执行结果 |
| `OrchestratorResult`（`agents/agent_orchestrator.py`） | `response`、路由、升级、`tools_used`、`tool_traces` | Orchestrator 产出；`api.chat()` 映射到对外 `ChatResponse` |

这张表只列排查时最常用的字段，不保证列出全部字段。要确认默认值、类型约束或新增字段，直接打开对应类；要确认字段**何时被赋值**，再搜索它的构造和更新位置。

### 1.6 文件夹怎样联动：三条不同的线

**启动装配线**：`api/main.py:lifespan()` 先创建 Memory、KnowledgeBase、ToolManager、Harness、Agent、Orchestrator；因此这些对象是共享依赖，不是每次请求重新初始化。找“某组件从哪里来、配置何时生效”，从 `lifespan()` 往下追。

**一次对话执行线**：`api.chat()` 先通过 `ConversationMemory.get_context()` 拿会话材料，再交给 `AgentOrchestrator.run()`；它请求 `IntentRecognizer.recognize()`，产生路由决定并调用领域 Agent；普通 Agent 经 `ContextBuilder` 和 `LLMClient` 回答，必要时通过 Harness 使用工具；Orchestrator 合并结果后统一写回会话，API 再返回 `ChatResponse`。找“谁调用谁”，沿这条线走。

**知识与工具支线**：文档先从 `/knowledge/add` 进入 `KnowledgeBase`，再刷新 BM25；聊天时由意图结果提出知识需求，Agent 经 `HarnessRuntime.handle_tool_call()` 调用 `ToolManager`，后者使用 `HybridRetriever`/`KnowledgeBase`/`BM25Index`，最终把片段送回 Agent 的 Context。找“为什么没有检索/检索错了”，不要从最终回答倒着猜，沿这条支线逐站检查。

可以把依赖方向简化为：

```text
api ──→ orchestrator ──→ intent recognizer
 │             │
 │             └──→ domain Agent ──→ ContextBuilder ──→ LLMClient
 │                       │
 ├──→ memory/             ├──→ SkillLoader
 │                       └──→ Harness ──→ ToolManager ──→ knowledge/
 └──→ response schema                         │
                                            └──→ tools/tool_functions.py

schemas/ 为上述各层提供可验证的数据结构；Trace/Monitor 观察执行，Evaluation 单独测试质量。
```

### 1.7 不知道字段或方法在哪儿时，怎样查

文档提供入口，**类型定义、调用点和测试才是当前代码的事实来源**。先搜声明，再搜使用，最后看测试。例如要追 `planned_tool_name`：

```bash
rg -n 'planned_tool_name' core agents schemas tests
rg -n 'class (IntentResult|RoutingDecision|ChatResponse)' core agents schemas
rg -n 'async def respond|async def handle_tool_call|def _persist_final_turn' agents harness
```

通常会先在 `IntentResult` 看到字段在哪里生成，再在 Orchestrator 看到怎样传给 Agent，最后在 Agent 看到它是否真的触发工具；只看字段声明不知道运行时会不会执行。若修改字段，还要检查它是否穿过 `IntentResult → RoutingDecision/Agent → OrchestratorResult → ChatResponse`，以及相应测试是否覆盖。

## 2. 各层的代码设计与修改边界

### 2.1 HTTP 与应用生命周期

`api/main.py` 的 `lifespan()` 在进程启动时创建 LLMClient、Redis/ChromaDB 适配器、知识库、ToolManager、Harness、Agent、Orchestrator、Evaluator 和 Monitor，并挂到 `app.state`。请求处理时复用这些对象；关闭时释放连接。长期记忆或知识库初始化失败可以降级，Redis 的真实读写失败则使 `/chat` 返回错误，不能悄悄当成“没有历史”。

`chat()` 只做传输层的事：解析 `ChatRequest`、确定会话 ID、读取 Memory、调用 Orchestrator、将 `OrchestratorResult` 映射到 `ChatResponse`。不要把新意图规则、工具权限或 Prompt 塞进 HTTP 路由。修改对外字段时，同步检查 `schemas/api.py`、`api/main.py`、内部结果模型和测试。其他路由——知识库、Skills、Trace、Monitor、Evaluation——也在 `api/main.py`，但不等于 `/chat` 主链路的一部分。

### 2.2 意图识别与路由

`IntentRecognizer.recognize()` 的输入是本轮文本及可选历史；输出 `IntentResult`，其中包含意图、置信度、结构化实体、领域分数、命中的主题证据、疑点、`information_need`、`planned_tool_name`、可支持的独立领域和 `subtasks`。代码主要分为：本地关键词证据 `_pattern_evidence()`；预设问题的字符 n-gram 相似度 `_template_match()`；疑点判断 `_ambiguity_reasons()`；可选 LLM 复核 `_llm_match()`；复合请求切分 `_build_subtasks()`；最后的融合、实体提取及信息需求判断。

修改时不要把“这是问句”和“它属于哪个业务主题”混为一谈。比如 `What is your refund policy?` 命中通用问句，但 `refund` 是更具体的业务证据；`information_need=knowledge` 才使后续检索有依据。`order_query`、`logistics_query` 需要相应 ID 才能被规划为只读预取工具。更改关键词、模板或阈值后，必须查看负例、相近领域以及 `tests/test_intent.py`，并运行 500 条本地回归。当前 `_template_match()` 不使用语义 Embedding；近义表达处理能力有限。

`AgentOrchestrator._make_decision()` 把 `IntentResult` 转成 `RoutingDecision`。明确转人工或严重紧急走 Escalation；其余按意图映射与领域分数选主 Agent。辅助 Agent 不只看分数接近，还受 `supporting_domains` 的独立问题证据约束。进入并行分支后，`_task_for()` 从 `subtasks` 找到该 Agent 的子问题，`_run_parallel()` 只传这段文本；Agent 的 Skill、RAG 查询、信息需求、实体和只读工具计划也使用任务级字段。`task_scoped=True` 还会给模型追加任务边界：历史里的其他主题或旧完整回答不得重新回答。`run()` 还负责请求用户补充信息、失败回退、结果合并和升级信号汇总。若是路由错，先看 `intent_recognized` 的证据与任务摘要，再看 `route_selected`；不要直接调主 Agent 的 Prompt 来掩盖上游分类错误。

### 2.3 Agent、Profile、Skill 和 Context

General、Technical、Billing 复用 `CustomerServiceAgent.respond()`，但各有 `AgentProfile`、角色提示和 Tool 范围。Profile 是角色契约：任务、工作步骤、输入/输出要求、转人工条件及 `tool_scope`。Skill 是针对退款、技术、物流等场景的人工维护指令，不是可执行 Tool。

在 `/chat` 中，Skill 的选择首先由 `AgentOrchestrator._skills_for()` 完成：它根据**当前 Agent 和任务级细粒度 intent**返回候选名称，例如 `refund`／`payment_issue` 对应 `refund` Skill，技术类 intent 对应 `technical` Skill。这个候选已经代表上游场景判断，因此 `SkillLoader` 只再检查 Skill 是否启用、是否允许当前 Agent 使用，不会要求用户文本第二次命中 Skill 的关键词。候选为空就不注入任何 Skill；`invoice` 和宽泛 `billing` 当前没有对应 Skill，不能错误地复用退款 SOP。

Skill 元数据中的 `keywords` 仍保留用于 Agent 被单独调用、没有来自 Orchestrator 的候选时进行关键词发现，并可在未来被 Embedding 相似度补充或替换。改 Skill 文件后可调用 `POST /skills/reload`；模型不会自行编辑 Skill。

领域 Agent 的执行顺序是：读取所需 Memory/AgentState → 在有知识需求时经 Harness 预取 `knowledge_search`，有可执行的只读计划时预取对应工具 → 选择 Skill → `ContextBuilder.build()` 组装本轮材料 → 调用模型，必要时进入 `_run_tool_loop()` → 更新 AgentState 和执行记录。已经预取的工具不会在这一轮再次作为模型可选工具暴露；其他工具仍必须在 Profile 范围内并经过 Harness。

`ContextBuilder` 只整理已加载的内容，不直接连 Redis、ChromaDB 或模型。模型看不到“数据库里的所有内容”，只看到近期历史、摘要、召回片段、选中 Skill、结构化状态和工具证据等本轮材料。检查回答偏差时，先确认正确证据是否进入 Context；如果证据本身没到模型，单改 Prompt 通常不能解决根因。模型缺少核实知识或真实业务数据时，Agent 的提示会要求它不要把猜测写成确定事实；这仍不是强制的逐句事实校验器。

### 2.4 RAG：入库与请求时检索是两条路径

**入库路径**：`POST /knowledge/add` 或 `/knowledge/upload` → `KnowledgeBase.add_documents_async()` → `knowledge/knowledge_base.py` 按英文 Markdown 标题/段落优先切 chunk，过长再按句子/词边界限制大小并添加相邻 overlap → ChromaDB 保存 chunk 及来源元数据 → API 尝试刷新进程内 BM25 索引。当前旧版 chunk 不会因为切片规则改变而自动重建；修改切片后，必须规划旧索引清理、重新入库和标注 chunk ID 的更新。

**检索路径**：`CustomerServiceAgent.respond()` 在知识需求成立时，先经 Harness 调用 `knowledge_search`；`ToolManager.search_with_rewrite()` 保留原查询并生成少量变体；`HybridRetriever.search_async()` 调用 ChromaDB Dense 与 BM25；RRF 融合后去重，再由 `ToolManager.rerank()` 本地排序，最后截取 Top-K。默认 BM25 开启、查询变体与重排使用本地方法。只有打开 `ARCLUME_RAG_LLM_ENABLED=true`，才可能额外用所配置的 Chat 模型改写与评分重排；没有独立部署的 Cross-Encoder/Reranker 模型。

ChromaDB 的默认 Embedding 行为由当前固定的 `chromadb==0.5.23` 决定；项目没有显式注入自选领域 Embedding Function。更换 Embedding 必须连同已有向量重建一起考虑。修改检索算法时，区分**召回没找到正确 chunk**、**找到但没排进 Top-K**、**排进 Top-K 但模型答错**；分别检查 `knowledge/`、`tools/tool_manager.py`、Agent/Context，不要用同一处修补所有问题。`evaluation/data/rag_cases.json` 依赖演示知识的 chunk ID，改入库逻辑后也要复核标签。

### 2.5 Tool 与 Harness

`tools/tool_functions.py` 放具体业务或演示函数及 `register_tools()`；`harness/executor.py` 的 `ToolDefinition` 描述名称、Schema、风险、允许的 Agent、超时/重试等，`ToolExecutor.execute()` 做参数校验与执行；`tools/tool_manager.py` 在此之上加入缓存、熔断、统计、降级和 RAG 搜索。`harness/policy.py` 的 `ToolPolicy.evaluate()` 只做允许/拒绝/要求审批的决定；`harness/runtime.py` 的 `handle_tool_call()` 串联 Policy、Executor、统一结果和 Trace。

模型返回的 ToolCall 不是直接调用 Python 函数的许可。工具须已注册、启用、在当前 Agent 范围内，并通过风险判断。高风险工具会得到 `requires_approval`，本次不会执行；当前尚无“批准后恢复执行”的 `/chat` 闭环。`ticket_create` 虽注册为演示高风险工具，但不在当前 Agent Profile 的工具范围内，也不连接真实工单系统。`order_query`、`logistics_query` 返回 Mock 数据；支付/退款当前没有真实实时查询接口。

新增 Tool 时至少检查两层权限：**注册项的 allowed_agents/risk_level** 与 **AgentProfile.tool_scope**。只改函数不改 Tool Schema，模型可能不会提供正确参数；只暴露 Schema 不做 Policy 检查则会破坏治理边界。Tool 失败、降级或审批结果应能在 `tool_traces` 和 Trace 中看到。

模型 Tool Call 不是所有供应商都只有标准字段。`core/llm_utils.py` 将 Tool Call 中的 `extra_content` 作为不解释的供应商扩展保留下来；`CustomerServiceAgent._run_tool_loop()` 会在把工具结果交回模型时，连同对应调用原样回传。Gemini 3 的 OpenAI 兼容接口会在 `extra_content.google.thought_signature` 中返回签名，并要求下一次工具循环带回它；遗漏会被 Gemini 拒绝为 400。普通 OpenAI 兼容模型通常没有这个字段，仍走相同路径。修改模型客户端或重建历史消息时，不要丢弃这种未知扩展字段；相关回归测试为 `tests/test_gemini_tool_signatures.py`。

### 2.6 Memory、AgentState 与最终回复

`ConversationMemory` 用 Redis 保存近期消息和当前会话摘要，达到阈值后压缩旧消息；`LongTermMemory` 用 ChromaDB 的 `episodic` 和 `user_profile` collection 保存可召回历史摘要与画像；`StateStore` 用 Redis 保存结构化 `AgentState`。它们都是跨请求数据，但用途不同：历史消息用于对话连续性，`AgentState` 是当前案件处理状态，ChromaDB 知识库则是业务资料，不是某个用户的会话记忆。

在 `/chat` 链路里，Agent 可以更新主 Agent 的 `AgentState`，但不负责把本轮对话写入 Redis；Orchestrator 选出**用户真正收到的最终文本**后，`_persist_final_turn()` 统一写入用户消息和 Assistant 回复。这样多 Agent 合并、请求用户补充信息和失败回退不会只保存主 Agent 的草稿。辅助 Agent 不写共享会话与状态。直接单独调用 Agent 时仍保留它原本的会话写回能力。Redis 写入不是跨消息事务：如果写入中途失败，仍可能出现部分写入，不能声称已有事务保证。

修改 Memory 时，先问清楚是要改变“数据存哪儿”“何时读取”“给模型看哪些”，再分别定位 `memory/`、`AgentOrchestrator`、`ContextBuilder`。不要把一次请求的临时 `Context` 当成持久数据库，也不要在多个并行 Agent 中重复写同一轮对话。

### 2.7 Trace、Monitor、Evaluation

`harness/trace.py` 的 `TraceRecorder` 保存有上限的进程内事件；`request_id` 把意图、路由、Agent、Tool、Memory 和请求结束事件串起来。重启服务或事件被挤出后不会保留；它不是审计数据库。`PerformanceMonitor` 周期性读取 Agent/Tool 指标，并可能对同类 Agent 实例的路由评分施加有限降权；它不评判回答事实是否正确，也不自动修改 Prompt 或 Skill。

`evaluation/` 是单独运行的质量检查。`python -m evaluation` 只测本地意图识别与确定性路由，不调用真实 `/chat`、模型、Redis 或 ChromaDB。RAG 检索与端到端对话走 API 评测，依赖当前知识库/模型配置；指标定义、数据限制及保存报告方式见 `evaluation_protocol_zh.md`。特别注意：当前 `POST /eval/run` 会保存端到端 baseline；提交仅含 RAG 用例的请求也可能覆盖配置的 baseline。不要在未确认输出路径时对需要保留的 baseline 运行演示评测。

## 3. 常见改动：从需求快速定位到代码

### 3.1 先用这张表判断入口

| 你想改变什么 | 首先看 | 连带检查 | 主要测试 |
|---|---|---|---|
| 某句话的意图、实体、知识/实时数据判断 | `core/intent_recognizer.py` | `agents/agent_orchestrator.py`；是否影响工具预取 | `tests/test_intent.py`、`tests/test_orchestrator_memory.py` |
| 新增、拆分或修改某个场景 Skill | `skills/<name>/SKILL.md`、`AgentOrchestrator._skills_for()` | front matter 的 `agents`/`enabled`；是否需要新增细粒度 intent；Context 长度与 Tool 边界 | `tests/test_skills.py`、`tests/test_request_plan_execution.py`、`tests/test_orchestrator_memory.py` |
| 主/辅 Agent 选择或请求用户补充信息 | `agents/agent_orchestrator.py` | `IntentResult.supporting_domains`、ResponseComposer、最终写回 | `tests/test_orchestrator_memory.py`、`tests/test_escalation.py` |
| 模型看到的角色或业务规则 | Agent 子类、`AgentProfile`、`skills/`、`core/context_builder.py` | Tool 范围、上下文长度、升级标记 | `tests/test_skills.py`、`tests/test_request_plan_execution.py` |
| 知识怎么切、存、找、排序 | `knowledge/`、`tools/tool_manager.py` | BM25 刷新、旧 chunk、RAG 标注集 | `tests/test_knowledge_chunking.py`、`tests/test_hybrid_rag.py` |
| 新增或收紧业务工具 | `tools/tool_functions.py`、`harness/` | Tool Schema、Profile scope、Trace、审批 | `tests/test_trace.py`、`tests/test_request_plan_execution.py` |
| 消息保存或多轮记忆 | `memory/`、`agents/agent_orchestrator.py` | `ContextBuilder`、画像、状态 | `tests/test_memory.py`、`tests/test_orchestrator_memory.py` |
| 对外 API 字段 | `schemas/api.py`、`api/main.py` | `OrchestratorResult`、OpenAPI 契约 | 对应模块测试及手工 `/docs` 检查 |

### 3.2 例子：退款政策没有检索

1. 先看 `/chat` 的 `intent`、`primary_agent` 和 `request_id`。若主意图成了 `query`，检查 `_pattern_evidence()`、`_template_match()` 与 `_information_need()`；若意图是 `refund` 却没有知识需求，重点检查 `_information_need()`。
2. 查看 `/traces/{request_id}` 的 `intent_recognized`、`route_selected`、`rag_completed`。若 `should_use_rag=true` 却 `attempted=false`，再看 Agent Profile 是否允许 `knowledge_search`、Harness 是否可用。
3. 有工具调用但 `result_count=0`，查 `/knowledge/stats`、`/search`、入库资料和 BM25/ChromaDB 状态。不要把空知识库误判为意图错误。
4. 有检索结果却回答错误，确认相关 chunk 是否进入 Context，再检查排序、过期文档、模型输出；目前没有强制引用/事实校验。
5. 修改后补一个正例和至少一个相近负例，运行意图、预取和 RAG 测试；若涉及检索质量，再对照标注样例检查 Top-K，而不只看模型说得是否流畅。

### 3.3 例子：新增一个只读工具

先在 `tools/tool_functions.py` 实现返回结构明确的函数并注册；在 `ToolDefinition` 设置输入 Schema、风险、允许的 Agent、超时与重试；再把工具加入对应 Agent 的 `tool_scope`。若它属于“信息需求明确就应取得”的实时数据，还要在 `IntentRecognizer._planned_tool()` 与 `CustomerServiceAgent.respond()` 的预取路径中建立参数映射；否则仅作为模型可选工具即可。最后检查无权限、参数缺失、超时、失败和成功五类路径，以及 `ToolResult`/Trace。需要写操作或审批时，不要把演示 Tool 直接扩展成真实业务执行：先设计身份验证、幂等和审批恢复。

### 3.4 例子：调整知识切片或检索排序

切片从 `KnowledgeBase._chunk_text()` 看，长段落边界在 `_split_long_paragraph()`，相邻重叠在 `_overlap_tail()`。只改 chunk 大小会改变已有标注 ID，也可能使 BM25 与 Dense 索引的内容版本不同；先用英文文档测试标题、长段、短段、重复导入，再在隔离数据集上重新建库。排序从 `HybridRetriever._rrf_fuse()` 和 `ToolManager.rerank()` 看，修改时记录候选召回率、Top-K 排名、延迟及是否调用额外模型。当前数据不足以直接断言某种 rerank 更好。

### 3.5 例子：修改多 Agent 回复或记忆

先区分“怎样从原句生成领域子任务”（`IntentRecognizer._build_subtasks()`）、“选择哪些 Agent”（`_make_decision()`）、“怎样把任务交给对应 Agent”（`_task_for()`、`_run_parallel()`）、“回复怎样合并”（`ResponseComposer`）以及“最终回复怎样写入”（`_persist_final_turn()`）。不要只在 Composer 做文本去重：如果多个 Agent 仍收到完整复合问题，它们会各自检索并生成重叠答案。任何改动都要检查 Agent 收到的当前消息及 RAG 查询已经按领域缩小、下一轮读到的是**合并后的对外回复**，并确认辅助 Agent 没有重复写会话。相关测试主要在 `tests/test_intent.py` 和 `tests/test_orchestrator_memory.py`。

## 4. 运行项目并观察代码行为

### 4.1 三种验证层级

| 层级 | 要做什么 | 需要什么 | 能证明什么 |
|---|---|---|---|
| 本地代码检查 | 单元测试、意图/路由评测 | Python 环境 | 规则、路由和模块契约在测试替身下是否符合预期 |
| 基础设施检查 | 启动 API，查看 `/health`，单独检索知识 | Redis、ChromaDB；检索默认可不调用模型 | 服务能否连接依赖、知识是否入库、检索链路是否返回结果 |
| 真实聊天检查 | 调用 `/chat`，追踪 `request_id` | Redis、可用的 Chat 模型；RAG 还需知识库 | 本次请求是否真正完成模型、工具、记忆和回复链路 |

建议按这个顺序验证，避免把模型、检索和路由的故障混在一起。`/health` 返回 200 不代表 `/chat` 已经可用：应用允许在没有模型 Key 或某些可选存储不可用时启动。

### 4.2 本地环境与配置

项目使用 Python 3.10 及 `requirements.txt`。以下命令均从仓库根目录执行；已有 `.venv` 时可以直接激活，不必重建。

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -q
python -m evaluation --smoke
```

配置保存在本地 `.env`，由 `api/main.py` 加载。不要提交真实 Key。至少确认：

| 配置 | 谁读取 | 用途 |
|---|---|---|
| `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` | `core/llm_utils.py` | OpenAI 兼容 Chat Completions 模型接口；真实 `/chat` 需要 |
| `REDIS_URL` | `api/main.py`、`memory/` | 近期消息、摘要和 AgentState；真实 `/chat` 需要可达的 Redis |
| `CHROMA_HOST`、`CHROMA_PORT` | `knowledge/`、`memory/long_term_memory.py` | 知识库、历史摘要及用户画像 |
| `ARCLUME_INTENT_LLM_ENABLED` | `api/main.py` | 有本地识别疑点时，可选模型复核；默认关闭 |
| `ARCLUME_RAG_LLM_ENABLED` | `tools/tool_manager.py` | 可选 LLM 查询改写和重排；默认关闭 |
| `ARCLUME_RAG_BM25_ENABLED` | `tools/tool_manager.py` | BM25 召回分支；默认开启 |
| `ARCLUME_MEMORY_LLM_ENABLED` | `memory/conversation_memory.py` | 额外的模型摘要/信息抽取；默认关闭 |

首次试运行若要控制模型调用次数，先保持三个可选 LLM 开关为 `false`。这只关闭额外调用，**普通 Agent 生成回复依然会调用 Chat 模型**。本地 Compose 的 Redis 默认要求密码；如果用 `docker compose up -d redis chromadb` 启动依赖，本机 Python 进程的 `REDIS_URL` 必须与 Compose 中的密码一致。ChromaDB 在宿主机映射到 8001 端口，容器内是 8000。

```bash
docker compose up -d redis chromadb
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

启动后先检查：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/knowledge/stats
```

如果缺少相关知识，可以通过 `POST /knowledge/add` 或 `POST /knowledge/upload` 导入英文客服资料，然后再测检索。`POST /search` 与 `GET /knowledge/search` 可以单独观察检索结果；默认本地改写/排序不消耗模型 Token，但打开 `ARCLUME_RAG_LLM_ENABLED` 后**可能**调用模型。

### 4.3 一次最小聊天及调试入口

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"What is your refund policy?","user_id":"demo-user","conversation_id":"demo-001"}'
```

保留响应中的 `request_id`。`message` 是用户实际看到的回复；`intent`、`primary_agent`、`supporting_agents`、`tools_used` 和 `tool_traces` 是调试线索。继续请求：

```bash
curl http://127.0.0.1:8000/traces/RETURNED_REQUEST_ID
curl http://127.0.0.1:8000/trace/tool/RETURNED_REQUEST_ID
```

这条政策问题应该先判断 Billing 与知识需求，再尝试 `knowledge_search`。若没有正确知识文档，可能有检索尝试但没有可用证据；不能只凭 `primary_agent=billing` 或 `use_rag=true` 认为回答已被知识库支持。

## 5. 测试、评测与改动检查

改动时先运行最接近的单元测试，再运行全套。测试使用替身，不会证明真实模型供应商或存储服务已经可用：

```bash
python -m unittest discover -s tests -p 'test_intent.py' -v
python -m unittest discover -s tests -q
python -m evaluation
python -m evaluation --smoke
git diff --check
```

当前 500 条 LLM 生成的英文合成意图样例可用于规则回归，但它不是自然流量，也尚未独立人工审核；同一批数据被反复用于调规则后尤其不能当作独立泛化证明。RAG 需要另外检查已入库文档和检索标签；真实模型回答则要看证据忠实度、延迟和费用。若想保存评测报告，用 `python -m evaluation --report <明确的输出文件>`，不要直接覆盖需要保留的历史结果。API 检索评测的 baseline 风险见前述 2.7 节和 `evaluation_protocol_zh.md`。

提交前至少确认：新增/修改行为有正反例；HTTP 契约与内部结果相符；Mock 与真实数据在文档和回复中没有混称；可选模型开关符合预期；错误路径可通过 Trace 定位；没有把 Key、客户数据或本地 `.env` 写进仓库。涉及新业务写操作时，还要检查审批、幂等、权限与审计，而不只看单元测试绿灯。

## 6. 按症状排查

| 症状 | 先看哪里 | 常见原因或下一步 |
|---|---|---|
| `/health` 200，但 `/chat` 503 | `llm_configured`、Redis 连接、API 日志 | 服务能启动不代表模型/Redis 已可用；校验本地 `.env` 与 `REDIS_URL` |
| `/chat` 502 | 模型调用错误及配置 | 检查 Base URL 是否指向兼容 Chat Completions 的路径、模型名、额度、网络和 API 返回的 `detail`；若只在 Tool Call 的第二次模型请求失败，检查是否完整回传了供应商扩展字段（例如 Gemini `thought_signature`）；不要贴出 Key |
| 意图或 Agent 错 | `intent_recognized`、`route_selected` | 分清主题证据、模板误命中、疑点与独立多领域判断 |
| 政策问题没用知识 | `should_use_rag`、`rag_completed`、Tool Trace | 先确定是没有计划、没有执行，还是执行后没结果 |
| `/search` 空结果 | `/knowledge/stats`、ChromaDB、BM25 文档数 | 知识未入库、旧 chunk、查询/排序不匹配，或某分支降级 |
| 模型声称查到了实时订单/退款 | `information_need`、`planned_tool_name`、`tool_traces` | 订单/物流只是 Mock；支付/退款没有真实数据接口，应纠正回答并设计事实核验 |
| 下一轮记忆不对 | Redis 消息/摘要、`_persist_final_turn()` | 核对 `user_id`/`conversation_id`、最终文本、Redis TTL 与部分写入 |
| 只看到部分 Trace | `/traces/{request_id}`、进程状态 | Trace 仅保存在本进程，可能因重启或容量上限而消失 |

排查顺序通常是：HTTP/依赖 → Intent → Routing → Agent/Context → Tool/RAG → 模型回答 → Memory 写回。先用 `request_id` 确认实际经过了哪一层，再改代码；不要只凭用户可见回答猜测内部路径。

## 7. 当前实现与限制

这个仓库目前是可演示的工程原型，不是已经接通生产客服系统的服务：真实订单、物流、支付、退款与工单集成未完成；高风险 Tool 只有阻断和“需审批”判断，没有批准后恢复执行；Trace 非持久化；RAG 评测规模小，尚不能证明 LLM 重排优于本地排序；Context 没有完善的 Token 预算，回答也没有强制来源核验。API 当前还缺少面向真实用户的认证、细粒度授权、隐私处理和限流。

阅读或修改代码时，应区分“代码已有入口”“可用 Mock 演示”和“真实业务已打通”。要推进生产化，优先补真实业务系统契约和安全边界，再用经过审核的英文客服用例建立意图、检索与回答的分层基线；不要仅凭一次 `/chat` 成功就宣布功能完成。

## 附录：接口与测试文件速查

| 用途 | 路径或文件 |
|---|---|
| HTTP 与交互文档 | `POST /chat`、`GET /health`、`GET /docs`；`api/main.py`、`schemas/api.py` |
| 检索与知识导入 | `GET /knowledge/search`、`POST /search`、`POST /knowledge/add`、`POST /knowledge/upload`、`GET /knowledge/stats` |
| 调试与监控 | `GET /traces/{request_id}`、`GET /trace/tool/{request_id}`、`GET /monitor`、`GET /metrics` |
| Skill 管理 | `GET /skills`、`POST /skills/reload` |
| API 评测 | `POST /eval/run`；`evaluation/`、`evaluation_protocol_zh.md` |
| 意图/路由测试 | `tests/test_intent.py`、`tests/test_orchestrator_memory.py` |
| RAG/预取测试 | `tests/test_knowledge_chunking.py`、`tests/test_hybrid_rag.py`、`tests/test_request_plan_execution.py` |
| Memory/Tool/运行状态测试 | `tests/test_memory.py`、`tests/test_trace.py`、`tests/test_escalation.py`、`tests/test_monitor.py` |
