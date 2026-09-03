# 第十一步：完整 RAG 和 Tool 治理

## 本步目标

前面的系统已经能够根据意图决定是否查询知识库，也能够通过 Harness 执行
`knowledge_search`。但当知识库内容变多、用户问题表达变复杂，单次向量查询
可能会出现两个问题：

```text
没有召回真正相关的内容
召回了内容，但排序和结果质量不够好
```

同时，知识库和其他业务 Tool 都属于外部依赖，可能超时、报错或暂时不可用。
因此本步同时解决两类问题：

```text
RAG 质量：尽可能找到正确、相关、少重复的知识
Tool 可靠性：工具出问题时可控、可降级、可追踪
```

本步不升级 Memory，不做历史消息压缩，也不实现外部 MCP 协议。

## 本步创建和修改的文件

### 新增文件

`tools/tool_manager.py`

作用：统一管理 RAG 检索和 Tool 运行治理。

核心类和方法：

```text
CircuitState
  记录熔断器的 CLOSED、OPEN、HALF_OPEN 状态

ToolStats
  记录每个 Tool 的调用次数、成功率、延迟、缓存命中和失败次数

CircuitBreaker
  判断 Tool 是否可以执行，并根据连续失败情况熔断或恢复

ToolManager
  execute()              统一执行 Tool，并加入缓存、熔断和 Fallback
  search_with_rewrite()  运行完整的 RAG 检索流程
  rewrite_query()        生成原始查询和查询变体
  rerank()               对合并后的候选结果进行重排
  stats_snapshot()       返回当前 Tool 的运行统计
```

调用关系：

```text
api/main.py
  → ToolManager
  → knowledge/knowledge_base.py

tools/tool_functions.py
  → ToolManager.search_with_rewrite()

harness/runtime.py
  → ToolManager.execute()
```

`docs/step11.md`

作用：记录本步的 RAG 流程、Tool 治理策略、配置项、接口变化和测试方法。

### 修改文件

`api/main.py`

作用：初始化 `ToolManager`，让 API 和客服 Agent 使用统一的 Tool 管理层。

主要变化：

```text
lifespan()          创建 KnowledgeBase、LLMClient 和 ToolManager
knowledge_search()  通过 Harness 调用完整 RAG 流程
tool_stats()        提供 Tool 运行统计接口
health()            返回 Tool 统计和 RAG 配置状态
```

`tools/tool_functions.py`

作用：定义实际的 Tool handler，并为每个 Tool 注册执行配置。

主要变化：

```text
knowledge_search()           调用 ToolManager 的增强 RAG 流程
knowledge_search_fallback()  知识库不可用时返回安全降级结果
register_tools()             注册 Tool、权限、超时、重试、缓存和 Fallback
```

本步还保留了订单查询、物流查询、创建工单等已有 Tool；它们没有改成外部 MCP
协议，仍然是应用内部可以直接调用的 Python handler。

`harness/executor.py`

作用：保留基础 Tool 执行能力，并为 Tool 增加治理配置。

主要变化：

```text
ToolDefinition.cache_ttl_seconds  配置缓存时间
ToolDefinition.supports_rerank    标记结果是否支持重排
ToolDefinition.fallback           配置失败后的降级函数
```

`harness/runtime.py`

作用：继续作为 Harness 的运行入口，并把 Tool 的执行状态记录到 Trace。

主要变化：

```text
handle_tool_call()  执行 Tool 后记录缓存、Fallback 和重排状态
tool_stats()        获取 ToolManager 提供的统计结果
```

`agents/customer_service_agent.py`

作用：让客服 Agent 使用统一的 ToolManager，并正确读取增强 RAG 返回的结果。

主要变化：

```text
_tool_context()        将 ToolManager 传给 Tool handler
_run_tool_loop()       继续通过 Harness 执行模型提出的 ToolCall
_record_tool_result()  保存本次 Tool 的使用和执行信息
```

`schemas/tool.py`

作用：扩展 Tool 执行结果的数据结构。

新增字段：

```text
cached          是否命中缓存
fallback_used   是否使用了降级结果
reranked        结果是否经过重排
```

`.env.example`

作用：提供本步 RAG 增强能力的配置模板。

新增配置：

```text
ARCLUME_RAG_LLM_ENABLED   是否启用模型查询改写和模型重排
ARCLUME_RAG_REWRITE_COUNT  查询变体数量
ARCLUME_RAG_MAX_CANDIDATES 多路召回的候选结果上限
```

`README.md`

作用：更新项目当前阶段、RAG 能力、ToolManager 和新增接口说明。

### 本步继续使用但没有修改的文件

```text
knowledge/knowledge_base.py  负责 ChromaDB 的基础文档查询
harness/policy.py             负责 Tool 权限、风险和 Agent Scope 判断
harness/trace.py              提供 Trace 数据结构
core/intent_recognizer.py     判断当前请求是否允许使用 RAG
core/context_builder.py       将检索结果组织成 Context
```

这些文件属于已有模块。本步通过调用它们完成治理链路，没有重复实现它们的职责。

## 当前目录

```text
arclume/
├── api/
│   └── main.py                         # 初始化 ToolManager 和检索接口
├── knowledge/
│   └── knowledge_base.py               # ChromaDB 文档写入和基础向量查询
├── tools/
│   ├── tool_functions.py               # Tool handler 和 ToolDefinition 注册
│   └── tool_manager.py                 # RAG 编排、缓存、熔断、Fallback、统计
├── harness/
│   ├── executor.py                     # 参数校验、超时、重试和结果规范化
│   ├── policy.py                       # Tool 权限、风险和 Agent Scope 判断
│   ├── runtime.py                      # Harness 入口和 Tool Loop
│   └── trace.py                        # 记录每次 Tool 决策和执行结果
├── schemas/
│   └── tool.py                         # ToolCall 和 ToolResult 数据结构
├── agents/
│   └── customer_service_agent.py       # 将检索结果注入 Context 或 Tool Loop
├── .env.example                        # RAG 治理配置示例
└── docs/step11.md                      # 本步骤记录
```

## 总体链路

### RAG 链路

```text
用户请求
  → IntentRecognizer 判断是否需要 RAG
  → Agent 或 /knowledge/search 请求 knowledge_search
  → Harness 检查权限和参数
  → ToolManager 检查缓存和熔断状态
  → 查询改写
  → 多路并行召回 ChromaDB
  → 合并去重
  → 结果重排
  → 截取 Top-K
  → 注入 Context 或返回给 Agent Tool Loop
```

### Tool 治理链路

```text
ToolCall
  → Agent Scope 和 Policy 判断
  → ToolManager 缓存检查
  → CircuitBreaker 判断是否放行
  → Executor 参数校验
  → Executor 超时控制
  → Executor 按配置重试
  → Tool handler 执行
  → 成功结果缓存或失败 Fallback
  → 更新统计
  → Harness Trace 记录
```

权限检查和执行检查仍然是两层：Agent 不能因为模型请求了某个 Tool，就直接绕
过 Policy 或 Executor。

## 一、意图门控

RAG 仍然不是每条消息都执行。`IntentRecognizer` 先产生
`should_use_rag`，再由 `AgentOrchestrator` 把这个结果传给 Agent。

```text
退款、订单、物流、发票、账单、账户、技术故障 → 允许 RAG
问候、满意反馈、明确转人工、未知意图         → 跳过 RAG
```

这里的“允许 RAG”不是强制模型一定要查，而是允许本次 Agent 使用
`knowledge_search`。如果模型支持 Tool Calling，它可以在需要证据时调用；如果
模型不支持 Tool Calling，Agent 继续使用已有的基础检索路径。

这样做的目的有两个：

```text
避免闲聊请求增加检索成本
避免无关知识污染模型 Context
```

## 二、查询改写

用户的原始问题经常很短、很口语化，或者同时包含多个条件。例如：

```text
“我上周买的东西还没到，物流一直没更新怎么办？”
```

检索前可以把它转换成多个更适合知识库搜索的查询角度：

```text
用户原始问题
├── 原始问题本身
├── 物流未更新和配送时效
└── 订单延迟和查件处理规则
```

### 当前实现

`ToolManager.rewrite_query()` 负责生成查询列表：

```text
默认最多 3 个查询
原始查询始终保留
查询长度受到限制
结果去重
```

默认情况下 `ARCLUME_RAG_LLM_ENABLED=false`，不额外调用模型。此时使用确定性
本地变体，主要包括去掉标点的原始问题和关键词组合。

如果以后打开配置，并且模型客户端已配置，则使用一次模型调用生成查询变体：

```env
ARCLUME_RAG_LLM_ENABLED=true
ARCLUME_RAG_REWRITE_COUNT=3
```

模型只负责提出搜索表达，不负责直接回答用户，也不负责决定 Tool 权限。解析失
败时自动退回本地查询变体。

## 三、多路并行召回

查询改写后，多个子查询通过 `asyncio.gather()` 并行访问 ChromaDB：

```text
query_1 ─┐
query_2 ─┼→ ChromaDB → 多组候选片段
query_3 ─┘
```

每个子查询不会只取最终 Top-K，而是先取较大的候选集合，再统一处理：

```text
candidate_k = max(top_k * 2, 6)
candidate_k 不超过 ARCLUME_RAG_MAX_CANDIDATES
```

这样可以避免某个子查询在早期就把可能有用的片段截掉。某一路召回失败时，剩
余分支仍然可以继续；只有所有分支都失败时，才进入 Tool Fallback。

## 四、合并去重

不同子查询可能召回相同的文档片段。`ToolManager._deduplicate()` 按以下顺序
确定片段身份：

```text
source + chunk
```

如果结果没有稳定的来源和 chunk 信息，则使用内容 hash。相同片段只保留一份，
并保留分数更高的版本。

这一步要在重排之前执行，否则同一段内容可能重复占用 Top-K 位置。

## 五、结果重排

基础 ChromaDB 查询结果主要反映向量相似度，但客服场景还需要考虑关键词是否
真正重合。因此当前实现有两级重排方式。

### 本地混合重排

默认不增加模型调用，使用：

```text
最终分数 = 0.7 × 向量相似度 + 0.3 × 关键词重合度
```

关键词重合度同时支持英文单词和中文字符，适合本地开发和无模型测试。

### 可选模型重排

当 `ARCLUME_RAG_LLM_ENABLED=true` 且模型配置完整时，候选片段会再经过一次模型
评分。模型只返回每个候选片段的相关性分数，系统仍然负责排序和截取，不能让模
型自行添加知识。

如果模型重排失败，自动使用本地混合重排：

```text
LLM rerank 成功 → 使用 LLM 分数
LLM rerank 失败 → 使用 local_hybrid 分数
```

最终只返回 `top_k` 条结果，当前 `top_k` 被限制在 1 到 20 之间。

## 六、结果注入 Context

本步不改变 Context 的职责。RAG 结果仍然是临时证据，不会直接写入长期 Memory。

基础路径：

```text
ToolManager 返回 results
  → CustomerServiceAgent 提取 results
  → ContextBuilder 写入 [Relevant knowledge]
  → LLMClient 生成回复
```

模型 Tool Calling 路径：

```text
Agent 请求 knowledge_search
  → Harness 执行 ToolManager
  → 结构化 ToolResult 返回模型
  → 模型根据结果生成回复
```

两条路径都使用同一个 `KnowledgeBase` 和同一个 `ToolManager`，不会在 Agent 内部
复制一套检索逻辑。

## 七、ToolDefinition 的治理字段

`harness/executor.py` 中的 `ToolDefinition` 增加了以下配置：

```text
cache_ttl_seconds：结果缓存时间，0 表示不缓存
supports_rerank：该 Tool 的结果是否可能经过重排
fallback：Tool 失败后的安全降级函数
```

当前知识库 Tool 的配置：

```text
timeout：10 秒
max_retries：1 次额外重试
cache_ttl：300 秒
supports_rerank：true
fallback：返回明确的空检索结果
```

订单和物流查询是低风险读取 Tool，设置了较短的缓存时间。高风险的
`ticket_create` 仍然先经过人工审批，本步没有降低它的风险等级。

## 八、ToolManager

`tools/tool_manager.py` 是本步新增的统一管理层。它继承当前的
`ToolExecutor`，所以不会破坏已有 Harness 接口。

### `CircuitBreaker`

使用三个状态：

```text
CLOSED：正常执行
OPEN：连续失败，暂时拒绝请求
HALF_OPEN：等待恢复后放行探测请求
```

默认连续失败 5 次后打开，60 秒后进入探测状态。熔断只针对 Tool 依赖，不会让
整个 FastAPI 进程停止。

### `ToolStats`

每个 Tool 当前记录：

```text
total：总调用次数
success：原始执行成功次数
failed：原始执行失败次数
cache_hits：缓存命中次数
fallback_count：Fallback 次数
average_latency_ms：平均耗时
consecutive_failures：连续失败次数
circuit_state：当前熔断状态
```

Fallback 返回给 Agent 的结果可以是成功的可解释降级结果，但统计中仍然保留原
始失败次数，不能把依赖故障伪装成真实成功。

### 缓存

缓存 key 由 Tool 名称和规范化后的参数组成：

```text
hash({tool_name, arguments})
```

只有成功且不是 Fallback 的结果会写入缓存。命中缓存时会重新绑定当前
`call_id`，避免一次请求复用另一次请求的调用标识。

### Fallback

知识库不可用时，Fallback 不会编造文档内容，只返回：

```text
results：空列表
degraded：true
message：知识检索暂时不可用
```

主客服链路仍然可以继续，让 Agent 明确表示需要人工核验或稍后重试。

## 九、Harness Trace

`HarnessRuntime` 在 Tool 执行结束时记录：

```text
success
error
duration_ms
cached
fallback_used
reranked
```

本步还把 Tool 结果中的这些字段同步带入 `/chat` 的 `tool_traces`，并在
`/tools/stats` 和 `/health` 中暴露 Tool 统计。这样可以区分：

```text
真的执行了 Tool
命中了缓存
执行失败后走了 Fallback
结果是否经过重排
```

更完整的请求级 Trace 持久化和长期查询仍然可以在后续 Monitor 阶段继续增强。

## 十、接口变化

### `GET /knowledge/search`

这个接口现在执行完整的知识检索链路，适合不调用客服模型时单独检查 RAG：

```text
GET /knowledge/search?query=退款多久到账&top_k=3
```

返回结构包含：

```text
query：原始查询
queries：实际使用的查询列表
results：最终 Top-K 结果
reranked：是否重排
rerank_method：local_hybrid、llm 或 none
cached：是否命中缓存
fallback_used：是否使用降级结果
degraded：是否有召回分支失败或依赖不可用
```

### `GET /tools/stats`

```text
GET /tools/stats
```

返回当前进程内各 Tool 的统计和熔断状态，后续由 Monitor 接管更长期的记录。

### `GET /health`

新增：

```text
tool_stats：各 Tool 运行统计
rag_llm_enabled：是否允许查询改写和模型重排
```

## 十一、一次退款查询流程

```text
1. /chat 接收“退款多久到账”
2. IntentRecognizer 识别为 refund，并将 should_use_rag 设为 true
3. BillingAgent 获得 refund Skill 和 knowledge_search Tool
4. 模型需要证据时请求 knowledge_search
5. Harness 判断 BillingAgent 是否在 Tool Scope 内
6. ToolManager 检查 300 秒缓存和熔断器
7. 生成最多 3 个检索查询
8. 并行查询 ChromaDB knowledge_base
9. 合并相同片段并进行本地混合重排
10. 返回 Top-K 片段给模型
11. 模型生成有依据的客服回复
12. /chat 返回 Tool 使用情况和 trace
```

如果模型没有启用 Tool Calling，则使用兼容的基础检索路径，但仍然经过
ToolManager 的 RAG 方法和治理逻辑。

## 十二、配置选择

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `ARCLUME_RAG_LLM_ENABLED` | `false` | 是否启用模型查询改写和模型重排 |
| `ARCLUME_RAG_REWRITE_COUNT` | `3` | 最多使用多少个查询变体 |
| `ARCLUME_RAG_MAX_CANDIDATES` | `30` | 多路召回候选结果上限 |
| `top_k` | `5` | 最终返回的知识片段数量 |
| `knowledge_search.cache_ttl_seconds` | `300` | 知识检索结果缓存时长 |
| `knowledge_search.timeout_seconds` | `10` | 单次知识 Tool 最大执行时间 |
| `knowledge_search.max_retries` | `1` | 超时或异常后的额外尝试次数 |

开发阶段保持 `ARCLUME_RAG_LLM_ENABLED=false`，不会因为测试 RAG 自动增加模型
调用。等基础召回和本地重排稳定后，再单独打开模型增强进行对比评测。

## 本步完成范围

```text
完成：意图门控后的统一 RAG 入口
完成：最多 3 个查询变体
完成：多查询并行召回
完成：候选合并和去重
完成：本地混合重排
完成：可选 LLM 查询改写
完成：可选 LLM 重排和失败回退
完成：知识 Tool 的 TTL 缓存
完成：Tool 超时和重试复用
完成：Tool 三态熔断器
完成：Tool Fallback
完成：Tool 运行统计
完成：Trace 中记录缓存、Fallback 和重排状态
完成：/knowledge/search 返回完整检索信息
完成：/tools/stats 提供本地统计查询
```

## 本步暂不处理

```text
Redis 工作记忆和 ChromaDB 长期记忆升级
历史消息压缩
用户画像和情景记忆
Dynamic Skills 元数据和热加载
Monitor 长期存储、告警和路由降权
Evaluation、LLM Judge 和回归检测
外部 MCP Server / Client 协议
```

## 本地验证

不需要真实模型调用：

```bash
source .venv/bin/activate
python -m compileall api agents core harness knowledge memory schemas tools
curl http://127.0.0.1:8000/health
curl "http://127.0.0.1:8000/knowledge/search?query=退款多久到账&top_k=3"
curl http://127.0.0.1:8000/tools/stats
```

当 ChromaDB 不可用时，知识检索接口应返回 `fallback_used=true` 和
`degraded=true`，但不会让服务进程崩溃。将
`ARCLUME_RAG_LLM_ENABLED` 保持为 `false`，上述测试不会产生模型费用。
