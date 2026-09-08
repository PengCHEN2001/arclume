# 第十六步：建立 Evaluation 评测系统

## 当前项目目录

```text
arclume/
├── api/
│   └── main.py                         # 初始化评测器并提供 /eval/run
├── core/
│   └── llm_utils.py                    # 支持评测器设置温度和输出长度
├── evaluation/
│   ├── __init__.py                     # 导出评测模块的公共对象
│   ├── __main__.py                     # 无模型的 Intent / 路由评测入口
│   ├── evaluator.py                    # 端到端对话评测和总体报告
│   ├── judge.py                        # 可选的大模型回答质量评分
│   ├── metrics.py                      # 分类和 RAG 排序指标
│   ├── models.py                       # 数据集、报告和回归数据结构
│   ├── regression.py                   # 两次评测报告的比较
│   ├── runner.py                       # 连接识别器和检索器的通用运行器
│   └── data/
│       └── cases.json                  # 当前的人工标注评测样例
├── schemas/
│   └── api.py                          # /eval/run 的请求结构
├── tests/
│   └── test_evaluation.py              # 评测指标、Judge 和报告测试
├── README.md                           # 更新评测能力和运行命令
└── docs/step16.md                      # 本步骤记录
```

## 本步目标

Monitor 负责观察系统运行得是否稳定；Evaluation 负责判断系统输出是否正确、是否
变好，以及修改后有没有退化。

本步建立三条评测入口：

```text
本地 CLI       → 无模型测试 Intent 和基础路由
通用 Runner    → 测试 Intent、路由和已标注的 RAG 结果
API /eval/run  → 真实运行 Agent，对回复做质量评分和回归比较
```

评测不会自动修改线上 Prompt、Skill、路由、Memory 或 Tool。它只产生报告，最后由
人工决定是否接受修改。

## 本步新增和修改的文件

### 新增目录和文件

`evaluation/models.py`

作用：保存评测输入和输出的数据结构，避免不同评测模块各自定义一套格式。

主要结构：

```text
IntentCase          # 一条带有 expected_intent 的识别样例
RetrievalCase       # 一条带有相关 chunk_id 的 RAG 样例
EvaluationDataset   # 从 JSON 读取的评测数据集
EvaluationReport    # CLI / Runner 使用的通用报告
RegressionIssue     # 一项发生退化的指标
RegressionReport    # 两个通用报告的比较结果
```

主要方法：

```text
IntentCase.from_dict()          # 从 JSON 对象创建识别样例
RetrievalCase.from_dict()       # 从 JSON 对象创建检索样例
EvaluationDataset.load()        # 读取 cases.json
EvaluationReport.save()         # 将报告保存为 JSON
EvaluationReport.load()         # 从 JSON 恢复历史报告
RegressionReport.passed         # 判断是否存在回归或缺失指标
```

`evaluation/metrics.py`

作用：提供不依赖大模型和第三方评测库的指标计算函数。

同一层函数：

```text
classification_accuracy()       # Intent 总准确率
macro_f1()                       # 所有类别 F1 的平均值
classification_metrics()        # 返回 accuracy 和 macro_f1
classification_details()         # 增加每个类别的 precision、recall、F1
recall_at_k()                    # RAG 前 K 个结果的召回率
precision_at_k()                 # RAG 前 K 个结果的准确比例
reciprocal_rank()                # 第一个相关结果的倒数排名
ndcg_at_k()                      # 同时评价多个相关结果的排序质量
retrieval_metrics()              # 聚合多条 RAG 样例的指标
```

`evaluation/runner.py`

作用：把通用指标连接到现有的 `IntentRecognizer`、路由函数和 Retriever。

同一层函数：

```text
evaluate_intent_cases()          # 运行 Intent，并可选检查 Agent 路由
evaluate_retrieval_cases()       # 运行检索并检查返回的 chunk_id
_resolve()                       # 同时兼容同步和异步函数
_label()                         # 统一读取字符串或 Enum 标签
```

这个文件不创建模型、Agent 或数据库。调用者通过参数传入识别函数和搜索函数，因
此测试时可以使用假的函数，正式运行时再连接真实模块。

`evaluation/regression.py`

作用：比较两次 `EvaluationReport`，判断共享指标是否下降过多。

```text
DEFAULT_TOLERANCES               # 各项指标默认允许的相对下降比例
compare_reports()                # 生成 RegressionReport
```

当前默认相对退化阈值为 `5%`。新报告增加指标不会失败；旧报告已有的指标在新报告
中消失，会被标记为缺失。

### `evaluation/evaluator.py`

作用：提供完整的 Agent 对话评测流程，并生成最终 API 报告。

#### `IntentTestCase`

一条端到端评测使用的 Intent 样例：

```text
message           # 用户消息
expected_intent   # 人工标注的正确 Intent
context           # 可选的额外评测上下文
```

#### `QualityScores`

保存一次回答的质量分数：

```text
relevance        # 是否回答了当前问题
accuracy         # 内容是否准确
completeness     # 是否覆盖必要信息
helpfulness      # 用户是否能根据回答行动
judge_failed     # Judge 是否调用失败
error            # Judge 失败原因
```

`overall` 会计算四个质量分数的平均值。`correctness` 是 `accuracy` 的兼容别名。

#### `EvalResult`

保存一个 Intent 或对话用例的结果：

```text
test_id          # 测试用例 ID
passed           # 是否达到通过阈值
scores           # 本用例的各项分数
detail           # 简短结果说明
metadata         # 原问题、回答、Intent、Agent 和错误信息
```

#### `EvalReport`

API 返回的总体报告：

```text
timestamp
total
passed
pass_rate
avg_scores
regressions
recommendations
results
```

主要方法：

```text
run()                      # 运行 Intent、单轮和多轮对话评测
_evaluate_intent()         # 调用 IntentRecognizer 并计算分类指标
_evaluate_dialog_case()    # 调用 Orchestrator 并逐轮评估回答
_judge_answer()            # 调用可选 LLMJudge
_detect_regressions()      # 和上一次报告或 baseline 比较
_recommendations()         # 根据低分指标生成改进建议
_load_baseline()           # 读取已有 baseline
_save_baseline()           # 保存当前报告
```

默认评测样例由两个常量提供：

```text
DEFAULT_INTENT_CASES        # 当前的 Intent 识别样例
DEFAULT_DIALOG_CASES        # 当前的单轮和多轮对话样例
```

### `evaluation/judge.py`

作用：使用一个可配置的大模型评价 Agent 的自然语言回答。它不会参与正常的
`/chat` 请求。

#### `JudgeResult`

保存 Judge 返回的四项分数和理由：

```text
relevance
accuracy
completeness
helpfulness
rationale
```

#### `LLMJudge`

核心方法：

```text
judge()                   # 请求模型评价一条回答
judge_many()              # 顺序评价多条回答
parse()                   # 解析并限制 JSON 分数范围到 0.0~1.0
```

模型必须返回 JSON。缺少某项分数时使用 `0.5`；JSON 无法解析时抛出
`JudgeError`。上层会把该用例标记为 `judge_failed`，不会让异常直接破坏整份报告。

通过阈值当前为：

```text
overall >= 0.75 → passed
overall <  0.75 → failed
```

如果没有配置可用模型，端到端对话评测仍会生成报告，但 Judge 分数会使用保守的
`0.5`，并标记为失败。这样可以检查评测链路是否通畅，但不能代表回答质量合格。

### `evaluation/__main__.py`

作用：提供无模型的本地 CLI。

运行流程：

```text
读取 evaluation/data/cases.json
→ IntentRecognizer().recognize()
→ 根据现有路由表计算基础 Agent 路由
→ evaluate_intent_cases()
→ 输出 EvaluationReport
→ 可选保存报告和比较 baseline
```

CLI 不启动 FastAPI、Redis、ChromaDB 或真实 Agent，也不会调用大模型。它适合在修改
Intent 规则后快速比较结果。

当前 `cases.json` 的 `retrieval_cases` 为空，因此 CLI 暂不连接实时知识库。RAG 的
评测函数已经准备好，等人工标注 `chunk_id` 后通过应用层 Runner 接入。

### `evaluation/data/cases.json`

作用：保存当前的人工标注样例。

Intent 样例字段：

```json
{
  "case_id": "refund-001",
  "message": "I want to request a refund",
  "expected_intent": "refund",
  "expected_agent": "billing"
}
```

RAG 样例字段：

```json
{
  "case_id": "refund-policy-001",
  "query": "How long does a refund take?",
  "relevant_chunk_ids": ["refund-policy::chunk-2"],
  "top_k": 5
}
```

`expected_intent`、`expected_agent` 和 `relevant_chunk_ids` 必须由人工确认，不能
让被评测的模型自己生成，否则评测没有独立标准。

## 修改文件

### `api/main.py`

作用：在应用启动时创建 `EndToEndEvaluator`，并提供评测接口。

启动阶段新增：

```text
app.state.evaluator = EndToEndEvaluator(
    orchestrator=app.state.orchestrator,
    recognizer=app.state.intent_recognizer,
    llm=app.state.llm,
    baseline_path=...
)
```

新增接口：

```text
POST /eval/run              # 运行默认或自定义评测样例
```

一次 API 评测流程：

```text
POST /eval/run
→ 解析 EvalRunInput
→ EndToEndEvaluator.run()
→ IntentRecognizer
→ Orchestrator
→ Agent / Memory / RAG / Skill / Tool
→ LLMJudge（如果模型可用）
→ baseline 回归比较
→ 返回 EvalReport
```

这个接口会真实调用 Agent 和模型，可能消耗 Token，也可能写入评测用的会话记忆，
不能放在每一次正常客服请求中自动执行。

### `schemas/api.py`

作用：定义 `/eval/run` 的外部请求格式。

```text
EvalIntentCaseInput       # message、expected_intent、context
EvalDialogCaseInput       # question 或 turns、用户和会话信息、参考答案
EvalRunInput              # intent_cases 和 dialog_cases
```

自定义请求示例：

```json
{
  "intent_cases": [
    {
      "message": "I was charged twice",
      "expected_intent": "payment_issue"
    }
  ],
  "dialog_cases": [
    {
      "turns": [
        "I want a refund",
        "My order number is #12345",
        "When will the refund arrive?"
      ]
    }
  ]
}
```

API 层的 Intent 输入目前不包含 `expected_agent` 和 `case_id`，它主要用于快速
运行自定义识别和对话样例；需要完整的离线路由报告时使用 `cases.json` 和 CLI
Runner。

### `core/llm_utils.py`

作用：让评测 Judge 可以控制模型调用参数。

`LLMClient.chat()` 新增可选参数：

```text
temperature       # Judge 使用 0.0，减少评分随机性
max_tokens        # 限制 Judge JSON 输出长度
```

正常客服调用不传这两个参数时，原来的默认行为不变。

### `README.md`

增加：

```text
evaluation/ 的作用和文件分布
无模型 CLI 命令
POST /eval/run 的使用方式
Evaluation 不自动修改线上系统的边界
```

### `tests/test_evaluation.py`

当前测试覆盖：

```text
分类 Accuracy、Macro-F1 和每类指标
Recall@K、Precision@K、MRR、NDCG@K
Intent / 路由 Runner
RAG Runner 读取 chunk_id
baseline 回归检测
Judge JSON 解析、分数限制和异常
端到端报告的 Intent、单轮和多轮结果
```

测试使用假的识别器、Retriever、Orchestrator 和 Judge，不需要 Redis、ChromaDB 或
真实 API Key。

## 两种报告结构

本步保留两种用途不同的报告：

```text
EvaluationReport
→ evaluation/runner.py 和无模型 CLI
→ 适合分类、RAG、baseline 的通用指标报告

EvalReport
→ evaluation/evaluator.py 和 /eval/run
→ 适合 Intent、对话质量、Judge 和端到端结果
```

它们都可以保存成 JSON，但字段不完全相同。后续如果需要统一离线和在线报告，
再增加统一的报告适配层，不在本步强行合并，避免破坏当前接口。

## 当前评测流程

### CLI：Intent 和基础路由

```text
evaluation/data/cases.json
→ EvaluationDataset.load()
→ IntentRecognizer
→ Intent 指标
→ Agent 路由指标
→ EvaluationReport
→ 终端输出或保存 JSON
→ 可选 compare_reports()
```

### API：端到端对话

```text
POST /eval/run
→ EndToEndEvaluator.run()
→ _evaluate_intent()
→ _evaluate_dialog_case()
→ Orchestrator.run()
→ Agent 生成回答
→ _judge_answer()
→ 计算 pass_rate 和 avg_scores
→ 检查 regressions
→ 生成 recommendations
→ 返回结果
```

多轮对话会把每轮的 user 和 assistant 内容放入下一轮的评测历史中，用来检查
Memory 和上下文是否连续工作。

## Baseline 规则

当前 `EndToEndEvaluator` 的比较顺序是：

```text
本次运行前同一进程最近一次报告
→ 如果没有，再读取 baseline 文件
→ 如果仍然没有，则不报告回归
```

当前默认：

```text
通过阈值：0.75
回归阈值：相对下降 5%
默认 baseline 路径：evaluation/baselines/baseline.json
```

当前实现每次 `run()` 后都会尝试保存报告到配置的 baseline 路径。正式使用前需要
决定是否改为“只有明确指定保存时才更新 baseline”，避免一次普通评测覆盖被认可的
历史基线。这个行为列为后续待定项。

## RAG 评测当前边界

已实现指标函数和通用 Runner：

```text
query
→ 现有 Retriever / ToolManager
→ 返回 ranked chunk_id
→ 对照 relevant_chunk_ids
→ Recall@K、Precision@K、MRR、NDCG@K
```

但当前没有足够的人工标注 RAG 数据，`cases.json` 中暂时没有检索用例。后续需要：

```text
补充真实客服问题
→ 为每个问题标记正确 chunk_id
→ 通过真实 ToolManager 运行检索
→ 保存检索报告
→ 观察混合检索、改写、重排是否真的提升
```

## 和 Monitor 的关系

```text
Monitor
→ 线上成功率、耗时、失败、熔断和告警

Evaluation
→ 离线 Intent、路由、RAG、回答质量和回归
```

Monitor 可以发现“某个 Agent 最近变慢了”；Evaluation 才能进一步检查“它的答案
是否准确”。两者都不会自动修改 Skill、Prompt 或线上路由。

## 本步暂不实现

```text
自动生成评测数据
自动生成 gold label
自动修改 Prompt
自动修改 Skill
自动发布评测建议
自动根据评测结果切换模型
在线请求自动触发完整评测
```

这些行为需要更多人工标注、稳定 baseline 和权限边界，当前只保留报告和建议。

## 测试和运行命令

运行全部测试：

```bash
./.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

无模型运行 Intent / 路由评测：

```bash
./.venv/bin/python -m evaluation
```

保存通用报告：

```bash
./.venv/bin/python -m evaluation \
  --report evaluation/baselines/local-intent-routing.json
```

使用 API 运行端到端评测：

```bash
curl -X POST http://127.0.0.1:8000/eval/run
```

查看 API 返回的重点字段：

```text
total
passed
pass_rate
avg_scores
regressions
recommendations
results
```

## 本步完成标准

```text
可以用人工标注样例评测 Intent
可以查看每类 Precision、Recall 和 F1
可以评测 Agent 路由
可以为 RAG 评测 Recall@K、Precision@K、MRR、NDCG@K
可以运行单轮和多轮端到端对话评测
可以使用可选 LLM Judge 评价回答
可以保存报告并检查 baseline 回归
可以通过 /eval/run 启动完整评测
评测失败不会自动修改线上系统
```
