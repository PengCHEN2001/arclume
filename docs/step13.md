# 第十三步：实现 Hybrid RAG

## 当前项目目录

```text
arclume/
├── api/
│   └── main.py                          # API 入口、资源初始化和健康检查
├── agents/
│   ├── customer_service_agent.py        # 客服 Agent
│   ├── escalation_agent.py              # 人工升级 Agent
│   └── agent_orchestrator.py            # Agent 编排和路由
├── core/
│   ├── context_builder.py               # 组织本次模型调用的 Context
│   ├── intent_recognizer.py             # 意图和 RAG 需求识别
│   └── llm_utils.py                     # 大模型调用封装
├── harness/
│   ├── executor.py                      # Tool 执行和基础治理
│   ├── policy.py                        # Tool 权限判断
│   ├── runtime.py                       # Agent Loop 边界
│   └── trace.py                         # 执行事件记录
├── knowledge/
│   ├── __init__.py                      # KnowledgeBaseError 等异常
│   ├── knowledge_base.py                # ChromaDB 文档写入和向量检索
│   ├── bm25_index.py                    # BM25 关键词检索
│   └── hybrid_retriever.py              # 向量与关键词检索的融合
├── memory/                              # 分层 Memory
├── schemas/                             # API、State、Context 和 Tool 数据结构
├── tools/
│   └── tool_manager.py                  # Tool 管理和 RAG 总流程协调
├── tests/
│   ├── test_memory.py                   # Memory 测试
│   └── test_hybrid_rag.py               # 混合 RAG 测试
├── data/demo_docs/                      # 本地示例知识文档
├── .env.example                         # RAG 和服务配置模板
├── README.md                            # 项目说明
└── docs/step13.md                       # 本步骤记录
```

## 本步目标

第 11 步已经有查询改写、多路召回、去重、重排和 Top-K，但召回主要依赖向量搜索。
本步增加关键词检索，让系统同时处理两类问题：

```text
语义相近但措辞不同       → ChromaDB dense retrieval
包含订单号、错误码、专有名词 → BM25 lexical retrieval
```

最终的 RAG 链路变成：

```text
IntentRecognizer 判断需要 RAG
→ 查询改写
→ ChromaDB 向量召回       ┐
→ BM25 关键词召回         ├→ RRF 合并
→ 合并去重
→ 本地重排或可选模型重排
→ Top-K
→ 注入 Context
→ Agent 生成回答
```

本步只负责把两种召回方式打通。更复杂的 Embedding 模型、Cross-Encoder、领域分词、
离线索引构建和完整评测留到后续阶段。

## 新增文件

### `knowledge/bm25_index.py`

作用：在应用进程中维护知识块的 BM25 关键词索引，不引入额外的向量数据库。

核心类：`BM25Index`

核心属性：

```text
k1                         # 词频饱和参数，默认 1.5
b                          # 文档长度归一化参数，默认 0.75
_documents                 # chunk_id 到知识块内容的映射
_term_frequencies          # 每个知识块的词频
_document_frequency        # 每个词出现在多少个知识块中
_average_document_length   # 全部知识块的平均长度
```

核心方法：

```text
replace(documents)         # 用 ChromaDB 当前全部知识块重建索引
upsert(documents)          # 插入或更新知识块
clear()                    # 清空索引
search(query, top_k)       # 返回关键词匹配结果
tokenize(text)             # 统一切分英文词、数字和中文字符
```

当前实现选择纯 Python BM25，原因是先减少部署组件，让关键词分支容易理解和测试。
索引只存在进程内，服务重启后从 ChromaDB 重新加载，不把 BM25 当作独立的长期数据源。

### `knowledge/hybrid_retriever.py`

作用：统一调用向量检索和 BM25 检索，并通过 RRF 生成一份候选结果。

核心数据结构：`HybridSearchResult`

```text
results                    # RRF 融合后的结果
dense_results              # 向量分支原始结果
bm25_results               # BM25 分支原始结果
degraded                   # 是否有分支失败或降级
```

核心类：`HybridRetriever`

核心属性：

```text
knowledge_base             # ChromaDB 向量检索适配器
bm25                       # BM25Index 实例
rrf_k                      # RRF 平滑参数，默认 60
_loaded_revision           # BM25 最近一次加载的知识库版本
_refresh_lock              # 防止多个请求同时重建索引
```

核心方法：

```text
initialize_async()         # 服务启动时加载 BM25
refresh_async()            # 知识库变化后重新加载 BM25
search_async()             # 并行召回并进行 RRF 融合
_rrf_fuse()                # 根据两个分支的排名合并结果
```

## 修改文件

### `knowledge/knowledge_base.py`

继续作为 ChromaDB 的唯一文档来源，增加三项能力：

```text
_revision                   # 文档写入后的本地版本号
get_indexed_chunks()        # 读取全部知识块和元数据
get_indexed_chunks_async()  # 异步读取全部知识块
```

向量搜索结果现在带有稳定的 `chunk_id`。BM25 使用同一批知识块和同一个 ID，才能在
两个分支返回同一个知识块时正确合并，而不是产生重复内容。

### `tools/tool_manager.py`

`ToolManager` 仍然负责 RAG 的整体流程，并增加：

```text
bm25_enabled               # 是否启用 BM25，默认 true
rrf_k                      # RRF 参数
hybrid_retriever           # 混合召回器
initialize_async()         # 启动时准备 BM25
refresh_hybrid_index()     # 文档更新后刷新 BM25
```

`search_with_rewrite()` 的变化：

```text
每个改写查询
→ 并行执行 dense 和 BM25
→ 收集 HybridSearchResult
→ 合并多个查询的结果
→ 去重
→ 现有本地重排或可选 LLM 重排
→ 返回最终 Top-K
```

返回结果新增：

```text
retrieval_mode             # hybrid 或 dense
fusion_method              # rrf 或 none
dense_count                # 向量分支召回数量
bm25_count                 # BM25 分支召回数量
fused_count                # 融合去重后的候选数量
degraded                   # 是否发生分支降级
```

### `api/main.py`

应用启动时初始化混合检索器。健康检查增加 BM25 状态，知识检索接口增加召回统计。
如果 BM25 索引准备失败，向量分支仍然可以继续工作；只有所有检索分支都失败时，
本次 RAG 才返回失败。

### `.env.example`

增加两个配置：

```text
ARCLUME_RAG_BM25_ENABLED=true
ARCLUME_RAG_RRF_K=60
```

将 `ARCLUME_RAG_BM25_ENABLED` 改成 `false`，可以临时切换到 dense-only 模式，
方便后续做召回效果和成本对比。

### `tests/test_hybrid_rag.py`

使用内存中的假的知识库测试三件事：

```text
BM25 能根据关键词找到对应知识块
HybridRetriever 能融合 dense 和 BM25 的同一结果
ToolManager 能返回混合检索的统计字段
```

测试不需要真实模型、Redis 或 ChromaDB 服务。

### `README.md`

更新当前阶段、RAG 目录、配置和测试说明。

## 当前选择

### 为什么同时保留 dense 和 BM25

只用向量搜索时，订单号、错误码、产品型号等精确字符串可能被语义相似度稀释；只用
BM25 时，用户换一种说法可能找不到对应文档。两者并行可以让精确匹配和语义匹配互相
补充。

### 为什么使用 RRF

两个分支的原始分数不是同一量纲，直接相加不稳定。当前只使用排名进行融合：

```text
RRF(chunk) = Σ 1 / (rrf_k + rank)
```

两个分支暂时使用相同权重，`rrf_k` 默认 60。未来有真实评测数据后，再决定是否为
不同业务意图设置不同权重。

### 为什么 BM25 先放在进程内

当前知识规模较小，进程内索引足够完成第一版，也不增加新的服务部署成本。ChromaDB
仍然保存完整知识块，服务启动或知识库更新后重新构建 BM25。未来数据量、并发量或多
实例部署明显增加时，再评估独立的搜索服务或持久化倒排索引。

### 当前没有做的内容

```text
没有引入 Cross-Encoder 或其他重型 Reranker
没有根据意图学习 BM25/dense 权重
没有做离线索引构建和版本化发布
没有做完整的 RAG 召回评测和自动调参
没有把 BM25 暴露为外部协议服务
```

这些不是本步阻塞项，后续应由 Evaluation 的结果决定是否加入。

## 一次知识检索请求

```text
用户问题
→ API 接收请求
→ IntentRecognizer 判断需要 RAG
→ ToolManager.search_with_rewrite()
→ 生成原问题和有限数量的查询变体
→ HybridRetriever 并行调用 ChromaDB 和 BM25
→ RRF 按 chunk_id 合并
→ 多个查询的结果再次去重
→ 本地重排，必要时才调用模型重排
→ 返回 Top-K 知识块
→ ContextBuilder 将结果放入 Context
→ Agent 生成最终回答
```

## 本步完成标准

```text
向量和关键词两条召回分支已经可以并行运行
两个分支的结果可以通过 chunk_id 合并
任意一条分支故障时，另一条分支可以降级工作
可以通过环境变量关闭 BM25
健康检查和知识检索接口能看到混合检索状态
本地测试不依赖真实模型和外部服务
```

测试命令：

```bash
./.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```
