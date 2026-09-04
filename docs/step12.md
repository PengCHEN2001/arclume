# 第十二步：升级分层 Memory

## 当前项目目录

```text
arclume/
├── api/
│   └── main.py                          # API 资源初始化和请求级 Memory 读取
├── agents/
│   ├── customer_service_agent.py        # 将 Memory 内容放入 Context，并写回消息
│   ├── escalation_agent.py              # 人工升级流程中的 Memory 写回
│   └── agent_orchestrator.py            # 将请求级 Memory Context 传给 Agent
├── core/
│   └── context_builder.py               # 渲染摘要、历史记忆和用户画像
├── memory/
│   ├── __init__.py                      # MemoryStoreError
│   ├── conversation_memory.py           # Redis 工作记忆、会话摘要和压缩
│   ├── long_term_memory.py              # ChromaDB 情景记忆和用户画像
│   └── state_store.py                   # Redis AgentState 保存
├── schemas/
│   └── context.py                       # Context 的 Memory 字段
├── tests/
│   └── test_memory.py                    # 不依赖外部服务的 Memory 测试
├── .env.example                         # Memory 配置模板
├── README.md                            # 当前项目阶段说明
└── docs/step12.md                       # 本步骤记录
```

## 本步目标

第 11 步之后，系统已经可以完成 RAG 和 Tool 治理，但 Memory 还只有 Redis 中的
最近消息。本步把 Memory 分成不同层次，让每种信息放到适合它的存储位置：

```text
当前对话的最近消息       → Redis 工作记忆
当前会话的压缩摘要       → Redis summary
跨会话的历史对话线索     → ChromaDB episodic
用户偏好和稳定实体       → ChromaDB user_profile
当前案件的结构化状态     → Redis AgentState
本次模型请求的临时材料   → Context
```

这里仍然明确区分：

```text
Memory：负责保存和读取信息
AgentState：负责保存当前案件状态
Context：负责组织本次模型调用要看到的信息
```

`AgentState` 和 `Context` 没有被合并到 Memory 中。Memory 只给它们提供数据。

## 本步新增和修改的文件

### 新增文件

`memory/long_term_memory.py`

作用：连接 ChromaDB，并管理两个长期记忆 collection。

核心类和方法：

```text
LongTermMemory
- chroma_host：ChromaDB 服务地址
- chroma_port：ChromaDB 服务端口
- local_path：允许本地模式时的持久化目录
- allow_local_fallback：服务不可用时是否允许本地模式
- _episodic：历史摘要 collection
- _profile：用户画像 collection
- initialize_async()：创建或连接两个 collection
- add_episodic_summary()：保存一次压缩后的历史摘要
- search_episodic()：按用户和问题检索相关历史摘要
- get_user_profile()：读取指定用户的画像
- update_user_profile()：合并实体和偏好并写回画像
```

`memory/conversation_memory.py`

作用：升级 Redis 对话记忆，同时协调长期记忆读写。

核心属性：

```text
_redis：异步 Redis 客户端
max_messages：工作记忆的最大消息数量，默认 20
ttl_seconds：工作记忆 TTL，默认 86400 秒
compress_at：触发压缩的消息数量，默认 15
retain_messages：压缩后保留的最近消息数量，默认 5
summary_ttl_seconds：Redis summary 的 TTL，默认 86400 秒
long_term_memory：可选的 ChromaDB 长期记忆适配器
llm_summary_enabled：是否允许额外调用模型生成摘要
```

核心方法：

```text
from_environment()：读取 Memory 配置并创建实例
add_message()：写入一条工作记忆，可选择是否触发压缩
get_messages()：读取最近消息并恢复时间顺序
get_summary()：读取当前会话摘要
get_context()：一次读取四类 Memory 内容
update_profile()：将实体和可选偏好写入用户画像
clear()：清除当前会话的 Redis 工作记忆和 summary
```

### 修改文件

`memory/conversation_memory.py`

在原有 Redis 最近消息的基础上增加：

```text
Redis summary
消息阈值压缩
ChromaDB episodic 写入
ChromaDB user_profile 更新
模型摘要开关和无模型本地降级
```

工作记忆仍然使用原来的 Key 格式，避免破坏已有数据：

```text
arclume:conversation:{user_id}:{conversation_id}
```

新增会话摘要 Key：

```text
arclume:summary:{user_id}:{conversation_id}
```

`schemas/context.py`

作用：把三类长期或半长期 Memory 的结果放进本次请求的 Context 结构。

新增字段：

```text
memory_summary：当前会话摘要
episodic_memories：相关历史摘要列表
user_profile：用户画像字典
```

`core/context_builder.py`

作用：把新增的 Memory 字段渲染成模型可读的 system message。

主要变化：

```text
memory_summary       → [Conversation summary]
episodic_memories    → [Relevant past conversations]
user_profile         → [User profile]
```

`api/main.py`

作用：服务启动时创建长期记忆适配器，并在 `/chat` 开始时读取完整 Memory Context。

主要变化：

```text
lifespan()：初始化 LongTermMemory 和升级后的 ConversationMemory
chat()：读取 get_context()，把结果传给 Orchestrator
health()：返回压缩阈值、保留数量和长期记忆模式
```

如果 ChromaDB 暂时不可用，API 继续使用 Redis 工作记忆，不让长期记忆故障阻断
客服请求。

`agents/agent_orchestrator.py`

作用：把 API 已经读取的 Memory Context 传给主 Agent 和辅助 Agent，避免每个
Agent 重复读取 Redis 和 ChromaDB。

主要变化：

```text
run()：接收 memory_context
_run_parallel()：把同一份请求级 Memory 传给多个 Agent
_execute()：将 memory_context 传入 Agent.respond()
```

`agents/customer_service_agent.py`

作用：把 Memory 内容送入 ContextBuilder，并在回复完成后写回消息和用户画像。

主要变化：

```text
respond()：接收请求级 Memory Context
respond()：将 summary、episodic 和 profile 放入 Context
respond()：助手回复写入后触发工作记忆压缩
respond()：写入当前识别出的实体和可选画像信息
```

当前用户消息写入时使用 `compact=False`，等助手回复也写入后再压缩。这样一次
完整的 user/assistant 交互会一起进入压缩过程，也避免模型使用压缩前后的混合快照。

`agents/escalation_agent.py`

作用：人工升级流程完成后，同样更新工作记忆和用户画像。

`.env.example`

作用：提供本步 Memory 配置：

```text
ARCLUME_MEMORY_MAX_MESSAGES
ARCLUME_MEMORY_TTL_SECONDS
ARCLUME_MEMORY_COMPRESS_AT
ARCLUME_MEMORY_RETAIN_MESSAGES
ARCLUME_MEMORY_SUMMARY_TTL_SECONDS
ARCLUME_MEMORY_LLM_ENABLED
ARCLUME_MEMORY_EPISODIC_TOP_K
ARCLUME_MEMORY_SUMMARY_MAX_CHARS
```

`README.md`

作用：更新当前阶段和四层 Memory 的存储方式。

`tests/test_memory.py`

作用：使用假的 Redis 和长期记忆对象，验证压缩、长期记忆注入以及故障边界，
不需要启动真实 Redis、ChromaDB 或模型。

覆盖的测试：

```text
工作记忆达到阈值后保留最近消息并写入 summary
episodic 和 user_profile 能进入 Memory Context
Redis 读取失败不会被静默转换为空历史
episodic 读取失败不会连带隐藏可用的 user_profile
```

## 四层 Memory 的职责

### 1. Redis 工作记忆

保存当前会话最近消息，主要用于保持多轮对话连续性。

```text
默认最多 20 条
默认 TTL 24 小时
最新消息在 Redis List 的前面
读取时恢复成从旧到新的顺序
```

它只保存用户和客服的对话消息，不保存 system prompt。system prompt 属于 Agent
配置，不属于用户记忆。

### 2. Redis 会话摘要

工作记忆达到 `compress_at=15` 后：

```text
取出旧消息
→ 保留最近 5 条
→ 生成不超过 800 字符的摘要
→ 写入 Redis summary
```

如果已经存在旧摘要，新的压缩结果会和旧摘要一起进入下一次摘要输入，避免摘要
只代表最近一次压缩。

默认 `ARCLUME_MEMORY_LLM_ENABLED=false`，此时使用不产生 Token 费用的本地事实
保留逻辑。开启后，才会使用模型生成摘要，并可额外提取明确的用户偏好和实体。

### 3. ChromaDB 情景记忆

Collection 名称：

```text
episodic
```

每次工作记忆压缩后，把压缩摘要和少量原始文本预览写入这个 collection。下一次
请求根据当前问题进行语义检索，只把相关历史摘要放入 Context，不把所有历史会话
全部发送给模型。

保存的主要信息：

```text
summary：压缩摘要
user_id：用户 ID
conversation_id：来源会话 ID
created_at：写入时间
full_text：旧消息的有限长度预览
```

### 4. ChromaDB 用户画像

Collection 名称：

```text
user_profile
```

每个用户使用一个稳定的 profile 文档。当前优先保存意图识别阶段已经提取出的
结构化实体；如果开启 Memory 的模型能力，还可以提取用户明确表达的偏好。

画像示例：

```json
{
  "user_id": "user-001",
  "entities": {
    "order_id": ["A-1001"]
  },
  "preferences": {
    "answer_style": "concise"
  }
}
```

画像是长期信息，不能把密码、一次性验证码、完整支付凭证等敏感信息主动写入。

## 工作记忆压缩流程

```text
当前会话消息数量达到 15
  → 取出旧消息，保留最近 5 条
  → 读取已有 Redis summary
  → 优先使用可选 LLM 生成事实摘要
  → LLM 不可用时使用本地事实保留逻辑
  → 新摘要写入 Redis summary
  → 新摘要写入 ChromaDB episodic
  → Redis 工作记忆重置为最近 5 条
```

压缩发生在助手回复写入之后，因此不会丢掉刚刚完成的完整交互。如果摘要模型或
ChromaDB 失败，Redis 工作记忆仍然可以继续工作。

## 一次 `/chat` 请求的运行流程

```text
1. API 接收 ChatRequest
2. 生成或恢复 conversation_id
3. ConversationMemory.get_context()
   ├─ 读取 Redis 最近消息
   ├─ 读取 Redis 当前 summary
   ├─ 查询 ChromaDB episodic
   └─ 读取 ChromaDB user_profile
4. API 将最近消息交给 IntentRecognizer
5. AgentOrchestrator 生成路由决策
6. Orchestrator 将同一份 memory_context 传给主 Agent 和辅助 Agent
7. 主 Agent 将用户问题、Memory、State、Skill、RAG 和 Tool 结果交给 ContextBuilder
8. ContextBuilder 渲染模型消息
9. 模型生成客服回复
10. 主 Agent 写入用户消息和助手回复
11. 助手回复写入后，达到阈值则压缩工作记忆
12. 将实体和可选偏好更新到 user_profile
13. API 返回 ChatResponse
```

Context 中的 Memory 排列为：

```text
AgentState
→ 请求分析
→ Skill
→ Conversation summary
→ Relevant past conversations
→ User profile
→ RAG knowledge
→ 最近 user / assistant 消息
→ 当前用户问题
```

当前用户问题仍然单独放在最后，避免它和历史消息混淆。

## 当前的成本和降级策略

```text
Redis 工作记忆：每次请求读取，成本低
Redis summary：达到阈值后写入
ChromaDB episodic：只有压缩时写入，读取时按当前问题检索
ChromaDB user_profile：回复完成后更新
LLM 摘要：默认关闭，避免额外 Token 消耗
LLM 画像提取：默认关闭，避免每次对话增加模型调用
```

长期记忆不是客服请求成功的硬依赖：

```text
Redis 正常、ChromaDB 不可用 → 继续使用工作记忆和 State
ChromaDB 正常、摘要模型不可用 → 使用本地摘要降级
长期记忆读写失败 → 记录日志，不阻断主客服回复
```

但 Redis 工作记忆属于当前请求的核心依赖，不能和 ChromaDB 使用相同的降级规则：

```text
Redis 读取或写入失败
  → ConversationMemory 抛出 MemoryStoreError
  → /chat 返回 503
  → 记录明确的 Memory 故障日志
```

这样不会把“系统没有读到历史记忆”伪装成“用户本来就没有历史记忆”。服务的
`/health` 主要报告进程和配置状态；真正的 Redis 可用性由 `/chat` 的实际读写和
Memory 测试验证。

情景记忆和用户画像在读取时分别处理：即使 episodic 查询失败，仍然尝试读取
user_profile；某一类长期记忆不可用时，不会让另一类也被一起丢弃。

## 本步完成范围

```text
完成：Redis 工作记忆继续保存最近消息
完成：Redis summary
完成：15 条消息触发压缩
完成：压缩后保留最近 5 条消息
完成：ChromaDB episodic
完成：ChromaDB user_profile
完成：相关历史摘要和用户画像注入 Context
完成：AgentState 继续独立保存
完成：可选 LLM 摘要和画像提取
完成：无模型本地降级
完成：长期记忆不可用时不阻断客服主链路
完成：明确区分 Redis 核心故障和 ChromaDB 可选故障
完成：增加 Memory 压缩、恢复和故障边界测试
```

## 本步暂不处理

```text
基于 Token 的精确 Context 预算
更复杂的摘要质量评测
敏感信息自动脱敏和合规审计
用户画像的删除、导出和隐私授权接口
跨用户的全局记忆检索
Monitor 长期保存和告警
Evaluation 和 LLM Judge
自动 Skill Evolution
```

## 本地验证

不需要真实模型调用。可以使用假的 Redis 和假的长期记忆对象验证压缩：

```bash
source .venv/bin/activate
python -m compileall api agents core harness knowledge memory schemas tools
python -m unittest discover -s tests -p 'test_*.py' -v
curl http://127.0.0.1:8000/health
```

重点检查：

```text
工作记忆达到阈值后只保留最近 5 条
Redis summary 存在
episodic 能返回历史摘要
user_profile 能返回用户实体
Context 中出现 summary、历史记忆和 profile
ChromaDB 不可用时 /chat 仍能使用 Redis 工作记忆
```

如果开启：

```env
ARCLUME_MEMORY_LLM_ENABLED=true
```

压缩时才会调用模型生成摘要；日常未达到压缩阈值时不会因为 Memory 自动增加
摘要调用。
