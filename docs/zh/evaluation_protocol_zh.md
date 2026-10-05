# Arclume 评测体系与运行方法

本文说明**当前评了什么、怎样评、如何亲自运行，以及还没有评到哪里**。设计与代码流程见 `项目设计与全链路.md`；评测入口主要在 `evaluation/` 和 `api/main.py`。项目以英文客服消息和英文知识文档为目标，所有质量结论都应基于与这个目标一致的数据。

> 状态：工程评测协议。现有数据主要用于开发回归，正式验收门槛、数据标注规范和独立测试集尚未确定。未来指标或框架都标为“计划”，不能当作当前已经实现的能力。

## 1. 评测应该分层，不只给一个总分

| 层 | 要回答的问题 | 当前入口 | 当前是否有可信结果 |
|---|---|---|---|
| 模块行为 | 切片、权限、写回、故障回退等代码契约是否正确 | `tests/` 单元测试 | 有测试通过/失败信号；不是效果准确率 |
| 意图与主 Agent | 主题标签是否正确、确定性主路由是否与标注一致 | `python -m evaluation` | 有 LLM 生成合成样例上的本地结果；不含模型回答 |
| RAG 检索 | 标注的相关 chunk 是否被召回并排进 Top-K | `/eval/run` 的 `retrieval_cases` | 有 18 条演示用例和指标实现；尚无确认过的当前运行结果 |
| Agent 对话 | 一次或多轮是否完成请求、回复是否有用 | `/eval/run` 的 `dialog_cases`、真实 `/chat` | 有执行与可选 LLM Judge 接口；尚无经过人工校准的英文质量基线 |
| 运行可靠性 | 错误、延迟、Tool 成功率随时间如何变化 | `/monitor`、`/metrics`、Trace | 是运行观测，不等于标注数据上的质量评测 |

这几层应该分开看。例如“退款政策回答错”可能是意图没认出、RAG 没启动、正确 chunk 没召回、排序没进 Top-K，也可能是模型拿到证据后仍答错。只看最终回复或一个总分，无法定位原因。

## 2. 当前数据与评测代码

| 数据/代码 | 当前内容 | 主要限制 |
|---|---|---|
| `evaluation/data/intent_cases_500.json` | 500 条 LLM 生成的英文合成消息、19 类意图、预期主 Agent | 样例与标签尚未独立人工审核，不代表真实用户分布；规则可能对这批样例过拟合 |
| `evaluation/data/cases.json` | 9 条本地冒烟样例 | 只用于快速检查入口，不能发布质量结论 |
| `evaluation/data/rag_cases.json` | `rag-smoke-v3`：18 条英文检索问题，标注 9 篇虚构演示文档的相关 chunk ID；多数 `top_k=3`，一条跨文档题为 `top_k=5` | 只覆盖小型演示知识；必须与当前文档、切片参数及索引版本一致 |
| `evaluation/evaluator.py` 默认对话样例 | 少量示例问答与多轮流程 | 当前默认样例包含中文，不适合作为英文客服产品基线；正式评测应传自定义英文用例 |
| `evaluation/metrics.py`、`runner.py` | 分类与检索指标、逐条错误记录 | 只计算输入数据给定的标签，不判断标签本身是否合理 |
| `evaluation/judge.py` | 可选 Chat LLM 对答案打分 | Judge 未经人工校准；模型评分不能代替业务事实核验 |

### 2.1 数据标注和版本原则

每条分类用例至少有消息、预期意图和预期主 Agent；检索用例至少有英文查询、相关 chunk ID 和 `top_k`。今后评多 Agent、工具与证据时，还需要标注预期辅助 Agent、信息需求、必须/禁止调用的工具、关键参数、期望证据以及允许的安全回答。

改文档、`CHROMA_CHUNK_SIZE`/`CHROMA_CHUNK_OVERLAP` 或切片代码，可能使 chunk ID 改变。当前 `rag-smoke-v3` 标签已按默认 500 字符上限、50 字符 overlap 的现有切片方式重新核对，并由 `tests/test_evaluation.py` 检查标签 ID 是否仍对应演示文件。**它不检查语义标签一定正确，也不自动清理已有 ChromaDB 中的旧 chunk。**若用旧索引运行，先在隔离环境重新建库，不能直接把旧库的低分解释成检索算法退化。

正式对比前固定：代码版本、数据集版本、知识库快照、Embedding/模型配置、BM25 与 RAG LLM 开关、Top-K、时间和重复运行次数。把规则反复调到同一份公开样例上之后，还需要保留不参与调参的测试集，并人工抽查标注。

## 3. 当前指标怎么计算、能说明什么

### 3.1 意图和确定性主路由

`evaluation/runner.py:evaluate_intent_cases()` 调用本地 `IntentRecognizer.recognize()`，将预测意图与标注比较；本地 CLI 另用一个简化的确定性映射函数得到预期主 Agent。报告给出意图/主路由各自的 Accuracy、Macro-F1，以及逐类 Precision、Recall、F1 和失败样例。

- **Accuracy**：预测正确数 ÷ 样例总数。
- **Precision / Recall / F1**：分别回答“预测为某类的有多少真是该类”“该类样例找回多少”“二者折中如何”。
- **Macro-F1**：各类别 F1 的简单平均，避免大类掩盖小类问题。

这里的主路由是“识别器输出 + 简化路由表”，**没有实例化完整 Agent，也没有评估辅助 Agent、RAG 启动、工具调用或模型回复**。它有助于定位上游分类回归，不应被称为“整个 Agent 系统准确率”。

### 3.2 检索：相关 chunk 有没有回来

`evaluate_retrieval_cases()` 把每条查询交给当前检索链路，读取返回的 `chunk_id`，与标注的相关 ID 比较。重复返回的 ID 只算一次；每条用例先单独计算，再对用例做简单平均。

| 指标 | 在本项目里的含义 |
|---|---|
| Recall@K | 标注的相关 chunk 中，有多少出现在前 K 条 |
| Precision@K | 前 K 个位置中，有多少是相关 chunk；即使实际不足 K 条，仍用 K 作分母 |
| MRR | 第一个相关 chunk 的排名倒数；前 K 条都没有则为 0 |
| nDCG@K | 相关 chunk 越靠前分越高；当前是二元相关/不相关标签 |

当前检索用例只判断**固定 ID 的 chunk 是否在结果中**，不判断最终回答是否忠于证据，也没有覆盖“知识库没有答案时应拒答”的情况。异常用例会记录为错误，并以空结果参与汇总；运行时同时看 `retrieval_failures`、`retrieval_errors`，不要只看均值。

### 3.3 对话与 LLM Judge

`EndToEndEvaluator` 会运行预设或自定义的 `dialog_cases`。每轮让 Orchestrator 真正执行，随后可用 `LLMJudge` 对回答的相关性、准确性、完整性、有用性各打 0～1 分；四项平均为本轮 `overall`，当前单条通过阈值是 `0.75`。多轮用例逐轮运行，不能把一条对话压成一个分数后隐藏失败的轮次。

**重要边界：**Judge 失败或未配置时，代码会用四项 `0.5` 占位并标记 `judge_failed`；Orchestrator 执行失败时还会记录 `execution_failed`。这两种分数都不能当成真实回答质量。当前 Judge 收到的 `context` 主要是该评测对话的先前轮次，**不是完整的检索证据**；因此即使 Judge 成功，也不足以证明回答对知识库逐句忠实。需要手工查看回答、检索片段和 Trace，并建立独立的证据一致性评测。

### 3.4 回归比较不是上线门槛

CLI 只有显式提供 `--baseline` 时才比较两个 JSON 报告。`evaluation/regression.py` 默认允许各指标相对下降不超过 5%；例如从 0.80 降到约 0.76 是相对下降 5%，不是下降 5 个百分点。历史基线有而新报告缺失的指标也算问题。这个阈值是代码默认值，**尚不是正式验收标准**；比较时还必须确保两次数据集与配置可比。

## 4. 怎样运行：从不调用模型到真实对话

以下命令从仓库根目录执行。需要 Python 依赖时先激活 `.venv`；启动 API 的配置方式见 `code_guide_zh.md`。实际运行前不要把真实 API Key 写进命令、报告或仓库。

### 4.1 最便宜：单元测试和本地意图/路由

```bash
python -m unittest discover -s tests -q
python -m evaluation --smoke
python -m evaluation
```

这组不调用真实 Chat 模型，也不需要启动 API、Redis 或 ChromaDB。看输出的 `metrics`、`counts`、`failure_preview` 和逐类指标；若要保留逐条内容，指定一个**新**报告路径：

```bash
python -m evaluation --report evaluation/reports/intent-local-YYYYMMDD.json
```

已有可比的历史 JSON 报告时，才使用 `--baseline <历史报告路径>`；该参数是读旧报告并比较，不会替你审核标签。`--verbose` 可以在终端展开逐条详情。修改意图规则后优先看低 F1 类别及错误样例，尤其是“普通问句覆盖业务主题”“两个领域误合并”和英文近义表达。

### 4.2 不用 Chat 模型：在隔离知识库上测 RAG 检索

当前 `rag-smoke-v3` 对应**按现有切片规则重新索引的九篇演示文档**。新增文件不会自动进入已有的非空 ChromaDB collection；最稳妥的做法是开一个独立、空的 ChromaDB 实例，而不是删除已有知识库或直接沿用旧持久卷。下面示例使用两个终端，8002/8010 端口可按实际占用调整。

终端 A：启动临时 ChromaDB，不挂载既有数据卷：

```bash
docker run --rm -p 8002:8000 chromadb/chroma:0.5.23
```

终端 B：从仓库根目录启动 API，并把会被 `/eval/run` 写入的 baseline 指向**唯一的临时目录**：

```bash
EVAL_SCRATCH_DIR=$(mktemp -d)
CHROMA_HOST=127.0.0.1 CHROMA_PORT=8002 \
ARCLUME_RAG_LLM_ENABLED=false \
ARCLUME_EVAL_BASELINE_PATH="$EVAL_SCRATCH_DIR/baseline.json" \
python -m uvicorn api.main:app --host 127.0.0.1 --port 8010
```

空知识库启动时会尝试导入 `data/demo_docs/`；首次默认 Embedding 模型可能需要本地下载，但这不是 Chat 模型 Token 调用。终端 C 检查 `/health` 的 `knowledge_base.ready`、`rag_bm25_documents`，以及 `/knowledge/stats` 的 chunk 总数，然后执行：

```bash
curl http://127.0.0.1:8010/health
curl http://127.0.0.1:8010/knowledge/stats
curl -X POST http://127.0.0.1:8010/eval/run \
  -H 'Content-Type: application/json' \
  --data-binary @evaluation/data/rag_cases.json
```

查看响应的 `retrieval.metrics`、`retrieval.counts`、`retrieval.failures`，而不是端到端对话分数。`rag_cases.json` 把意图与对话用例设为空，且 RAG LLM 开关关闭，因此该示例不需要真实 Chat 模型。**但 `/eval/run` 仍会先写一次空的端到端 baseline**，所以必须先设置临时路径。若演示文档未导入、旧 chunk 与新 chunk 混用，先解决索引版本，再讨论 Recall@K。没有 Docker 时也可连接自己启动的隔离 ChromaDB 实例，保持相同的“空库 + 当前数据 + 临时 baseline”原则。

### 4.3 真实模型：先做少量 `/chat` 人工检查

配置好 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`、Redis 与所需知识库后，建议先关闭三个额外 LLM 开关，只让普通 Agent 回答消耗模型请求。依次试问候、退款政策、登录与重复扣费复合问题、人工转接；保存每次 `request_id`，查 `/traces/{request_id}` 与 `/trace/tool/{request_id}`。逐条记录：意图、主/辅 Agent、是否计划知识/实时数据、工具是否真执行、取得什么证据、回答是否引用正确事实、是否出现虚构操作。

这一步是**人工端到端检查**，不是自动计算的通过率。若要求可重复比较，应把问题、预期行为和人工判定写成独立英文用例，再固定模型版本、采样参数、知识库快照与运行次数。

### 4.4 真实模型：用自定义英文用例调用 `/eval/run`

当确实要测当前的自动对话评测时，先用 `ARCLUME_EVAL_BASELINE_PATH` 为这次运行选择可覆盖的临时路径并**重启 API**，确认模型与 Redis 可用，再只提交少量英文用例：

```bash
curl -X POST http://127.0.0.1:8000/eval/run \
  -H 'Content-Type: application/json' \
  -d '{"intent_cases":[],"dialog_cases":[{"question":"How long can I request a refund?","reference_answer":"Customers can request a no-questions-asked refund within seven days of purchase."}]}'
```

这会真的运行 Agent，并可能额外调用 Judge；工具循环或开启可选 LLM 开关还会增加请求次数。不要把默认 `/eval/run` 的中文对话样例当成英文客服基线。检查返回的 `results[].metadata.judge_failed`、`execution_failed`、实际回答与 `avg_scores`；失败时的 0.5 占位分必须排除出质量结论。**目前没有记录经过人工确认的真实模型端到端分数。**

## 5. 结果、报告与已知陷阱

### 5.1 已有的无模型结果

| 日期与范围 | 意图 Accuracy / Macro-F1 | 主路由 Accuracy / Macro-F1 | 解读 |
|---|---|---|---|
| 2026-09-16，500 条 LLM 生成样例的历史运行 | 72.80% / 0.7380 | 80.20% / 0.8026 | 当时实现的历史参考；未保存逐条 JSON，不能当成当前代码结果 |
| 2026-10-04，当前工作区同一份 500 条 LLM 生成样例 | 92.20% / 0.9213 | 96.60% / 0.9710 | 本地识别器 + 简化确定性主路由；意图错 39 条、主路由错 17 条；未调用模型/API/Redis/ChromaDB |

两次运行可以显示这批 LLM 生成样例上的变化，但没有独立隐藏集、人工复核或真实流量，不能由此推断线上准确率。RAG `rag-smoke-v3` 当前只核对了标注 ID 与现有切片的一致性，**尚未在本协议中记录有效的真实检索指标**；真实模型回答和 LLM Judge 也尚无确认结果。

同日的代码检查为 69 个单元测试通过、9 条本地冒烟用例通过；其中包括复合问题按领域生成子任务、并将不同子问题交给 General 与 Billing Agent 的回归测试。两者都没有调用真实模型。单元测试中的模拟故障日志是用于验证回退路径，不代表这次测试失败。

### 5.2 特别注意 baseline 与失败占位分

`EndToEndEvaluator.run()` 每次会保存自己的报告；API 默认路径为 `evaluation/baselines/baseline.json`，可用 `ARCLUME_EVAL_BASELINE_PATH` 更改。即使请求只含检索用例，API 仍会先运行空的端到端评测并保存报告，再把检索结果加到**响应**中；保存的 baseline 不包含随后附加的 RAG 指标。运行检索评测前使用临时路径，不要覆盖需要保留的报告。长期应把检索报告与端到端 baseline 保存逻辑拆开。

判读报告时至少先检查：样例数是否正确、是否有执行异常、Judge 是否成功、用例标签/索引是否匹配、是否使用相同配置。若数据不同、知识库不同或 Judge 失败，不能仅凭两个 `pass_rate` 或平均分判定版本优劣。

## 6. 下一阶段评测计划（尚未实现）

### 6.1 先补数据，再补高级分数

优先建立小型、人工审核的英文客服金标准集，覆盖明确问候、政策、订单/物流、登录、重复扣费、多领域组合、无答案、否定/反问、依赖历史、要求执行高风险操作与转人工。每条记录预期主题、主/辅 Agent、信息需求、允许/禁止的工具、相关证据、可接受答案要点和必须拒绝的虚构事实。分开发集与保留测试集，记录标注分歧；对模型/Prompt 随机性至少重复运行若干次并报告波动。

### 6.2 RAG：从“找到了”走到“答得有根据”

保持现有 Recall@K/MRR/nDCG 作为检索第一层，再增加：查询改写前后命中率、BM25/Dense 单路与混合对照、Top-K 与 rerank 对照、无答案时的误答率。接着按“问题 → 召回片段 → 最终回答”标注**证据是否足够、回答中的主张是否可由片段支持、有没有遗漏或编造政策**。回答相似度只能说明措辞/语义接近参考答案，不能单独识别错误金额或天数。

可参考 [RAGChecker 论文](https://arxiv.org/abs/2408.08067) 的检索/生成细粒度诊断，或 [Ragas 官方指标目录](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/) 中的 context precision/recall、faithfulness、response relevancy、semantic similarity。它们目前没有接入 Arclume，也没有相应分数。选型应比较人工一致性、额外模型费用和可复现性，而不是只看框架输出的一个数字。

### 6.3 Agent：评最终答案，也评行动轨迹

当前本地路由评测只覆盖主 Agent。下一步应单独统计：主/辅 Agent 集合准确率、RAG 启动 Precision/Recall、需要工具时的 Tool Call Recall、禁止工具的违规率、参数正确率、Harness 审批拦截率、多轮状态连续性、失败回退成功率，以及最终是否真正完成用户目标。对客服尤其要测“没有真实订单/支付数据时不声称查到结果”“高风险操作没有批准时不执行”“升级提示没有冒充已建工单”。

行动轨迹可用确定性规则比较预期和实际的 Agent/Tool/Policy/Trace 事件，再用人工或经过校准的 Judge 评价较开放的回复；参考 [Ragas Agent/Tool 指标](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/) 或 [LangSmith 评测类型说明](https://docs.langchain.com/langsmith/evaluation-types/) 设计用例即可，不必为得到这些指标而强制迁移运行框架。性能还应记录请求成功率、p50/p95 延迟、模型/工具调用次数和成本，并在依赖超时、检索为空及多 Agent 部分失败时重复验证。

## 7. 新结果记录模板

每次有可复现的基线或重要对照时，在此文档追加简短摘要；逐条详情另存 JSON。不要覆盖旧结果，也不要把真实 Key、客户信息或未脱敏会话写入报告。

```text
日期 / 代码版本：
评测目标与当前/未来状态：
数据集版本、样例数、标注方式：
知识库和 chunk/Embedding 版本：
模型、供应商、采样参数及可选开关：
执行命令或请求、报告路径：
有效样例数、执行错误数、Judge 失败数：
分层指标及逐类/逐场景失败：
相对旧版本的变化、是否可比：
人工复核结论、已知限制和下一步：
```
