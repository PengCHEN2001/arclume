# 第十七步：后端能力收口

## 本步目标

前面的核心 Agent 主链路已经完成。本步把运行接口、Trace 查询、知识库管理、意图反馈和部署配置补齐，形成一个可以配置 API Key 后直接验证的后端版本。

本步不改变已有的 Agent、Memory、Context、RAG、Tool、Harness、Skill、Monitor 和 Evaluation 设计，只补上它们之间缺少的外部入口和工程收尾。

## 本步涉及的目录

```text
arclume/
├── api/
│   └── main.py                         # 补充 CORS、知识库接口和 Tool Trace 接口
├── config/
│   ├── nginx/
│   │   └── nginx.conf                  # 反向代理配置
│   └── prometheus.yml                  # Prometheus 抓取配置
├── core/
│   └── intent_recognizer.py            # 增加人工反馈样例和缓存统计
├── evaluation/
│   └── evaluator.py                    # 暴露独立 IntentEvaluator
├── harness/
│   └── runtime.py                      # 增加 Tool Trace 查询方法
├── schemas/
│   └── api.py                          # 增加知识库导入请求模型
├── tests/
│   ├── test_evaluation.py              # 增加独立 IntentEvaluator 测试
│   ├── test_intent.py                  # 增加 Intent 反馈和缓存测试
│   └── test_trace.py                   # 增加 Tool Trace 查询测试
├── .env.example                        # 增加评测、CORS 配置
├── Dockerfile                          # 补充 Monitor 和 Evaluation 代码
├── docker-compose.yml                  # 补充密码、数据挂载、Prometheus、Nginx
├── README.md                           # 更新阶段和接口说明
└── requirements.txt                    # 增加文件上传依赖
```

## 本步补充内容

### 1. 知识库管理接口

当前增加三个入口：

```text
POST /search
POST /knowledge/add
POST /knowledge/upload
```

`POST /search` 和已有的 `GET /knowledge/search` 使用同一套检索逻辑：

```text
查询改写
→ Dense + BM25 并行召回
→ RRF 合并
→ 去重
→ 本地或模型重排
→ 返回 Top-K
```

`POST /knowledge/add` 接收批量 JSON 文档，文档进入 ChromaDB 后会尝试刷新 BM25 索引。

`POST /knowledge/upload` 支持：

- `.md`
- `.txt`
- `.json`

JSON 文件格式为：

```json
[
  {
    "title": "Refund Policy",
    "content": "..."
  }
]
```

上传文件大小限制为 10 MB。上传失败不会绕过 KnowledgeBase 的切片和索引逻辑。

### 2. Tool Trace 查询接口

Harness 现在可以把一次请求中的 Tool 事件整理成单独的查询结果：

```text
GET /trace/tool/{request_id}
GET /trace/tools?limit=20
```

一次 Tool Trace 中会保留：

- 模型是否提出 Tool Call
- Policy 是否允许执行
- Tool 是否成功
- 是否使用缓存
- 是否使用 Fallback
- 是否发生重排
- 执行耗时和错误信息

原有的 `GET /traces/{request_id}` 仍然保留，用于查看完整请求链路。

### 3. Intent 人工反馈能力

`IntentRecognizer.learn()` 可以把人工确认过的样例加入本地相似度模板：

```python
recognizer.learn("用户的真实表达", IntentCategory.REFUND)
```

它只影响当前进程中的本地识别样例，不会自动修改文件，也不会自动发布线上规则。

同时增加 `cache_stats()`，用于查看识别缓存命中、未命中和人工新增样例数量。

### 4. 独立 Intent Evaluation

`evaluation/evaluator.py` 现在同时提供：

```text
IntentEvaluator      # 单独评测 Intent
EndToEndEvaluator    # 评测完整对话链路
```

这样可以只测试 Intent，也可以运行完整的对话、Judge 和 baseline 评测。

### 5. CORS 和部署配置

API 增加 CORS 支持，开发环境默认允许所有来源。生产环境通过：

```text
ARCLUME_CORS_ORIGINS=https://your-frontend.example.com
```

进行限制。

Docker Compose 现在包含：

```text
Redis
ChromaDB
Arclume API
Prometheus
Nginx
```

Redis 使用密码和 AOF 持久化。ChromaDB、Evaluation baseline、Skills 和日志均有持久化或挂载位置。

## 当前一次测试请求的路径

```text
客户端
  → FastAPI /chat
  → Redis 读取工作记忆和 AgentState
  → IntentRecognizer
  → AgentOrchestrator
  → AgentProfile 选择角色、Skill 和 Tool 范围
  → ContextBuilder
  → Harness Policy
  → Tool / RAG / 大模型
  → Agent 回复
  → Redis 和 ChromaDB 写回 Memory
  → Monitor 记录指标
  → API 返回 response、intent、Agent、Tool Trace
```

如果测试知识库接口，则从 `POST /search` 或 `GET /knowledge/search` 开始，不会调用客服大模型。

## 本步验证

在项目虚拟环境中安装依赖：

```bash
python -m pip install -r requirements.txt
```

运行本地单元测试：

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

预期结果：全部测试通过。

启动 API：

```bash
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

先检查：

```bash
curl http://127.0.0.1:8000/health
```

然后再配置真实模型信息测试 `/chat`。Redis 必须可用；ChromaDB 不可用时可以根据配置降级，但 RAG 相关接口需要可用的知识库。

## 本步没有改变的内容

以下内容仍然保持当前设计：

- 不使用外部 MCP 协议。
- 不自动生成、修改、发布或回滚 Skill。
- 订单、物流和工单 Tool 仍然是演示实现。
- 多 Agent 回复默认不额外增加一次模型合并调用。
- RAG 的正式质量仍需要后续补充人工标注数据。
- 前端暂不纳入本阶段。

这些不是主链路缺失，而是后续接入真实业务和优化质量时再处理的内容。

## 完成标准

- 知识库可以通过 JSON 或文件上传接口更新。
- 更新知识库后可以刷新或自动重建 BM25 索引。
- Tool Trace 可以按请求查询，也可以查询最近请求。
- Intent 支持人工反馈样例。
- Evaluation 同时支持独立 Intent 和端到端评测。
- Dockerfile 不遗漏已被 API 导入的模块。
- Compose 具备 API、Redis、ChromaDB、Prometheus 和 Nginx 的部署配置。
- 本地单元测试全部通过。


