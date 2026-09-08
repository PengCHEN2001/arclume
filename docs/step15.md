# 第十五步：建立 Monitor 监控系统

## 当前项目目录

```text
arclume/
├── api/
│   └── main.py                          # 启动 Monitor，并提供 /monitor、/metrics
├── agents/
│   └── agent_orchestrator.py            # 暴露 Agent 指标并接收路由惩罚
├── monitor/
│   ├── __init__.py                      # Monitor 包声明
│   └── performance_monitor.py            # 指标采集、异常检测、告警和建议
├── tools/
│   └── tool_manager.py                  # 暴露 Tool 运行统计
├── tests/
│   └── test_monitor.py                  # Monitor 行为和生命周期测试
├── requirements.txt                     # 增加 Prometheus 客户端依赖
├── .env.example                         # Monitor 和 Prometheus 配置模板
├── README.md                            # 更新当前项目能力
└── docs/step15.md                       # 本步骤记录
```

## 本步目标

前面的 Agent、Tool、RAG 和 Harness 已经会在运行时产生一些基础统计。本步不新增
模型调用，也不改变客服主流程，而是把这些统计集中起来，回答三个问题：

```text
Agent 和 Tool 当前运行是否正常？
有没有明显的失败或延迟异常？
监控结果能不能为后续路由调整和 Evaluation 提供数据？
```

本步的运行关系：

```text
AgentOrchestrator / ToolManager
            ↓ 读取已有统计
PerformanceMonitor
            ├── 阈值检查
            ├── 滑动窗口异常检测
            ├── Alert 和 Suggestion
            ├── routing penalty → Orchestrator
            └── /monitor、/metrics
```

## `monitor/performance_monitor.py`

### `Severity`

表示告警等级：

```text
INFO
WARNING
ERROR
CRITICAL
```

### `Alert`

保存一次异常或阈值告警：

```text
severity       # 告警等级
metric         # 指标名称和对象，例如 agent_success_rate:technical_0
message        # 给人看的说明
value          # 当前值
threshold      # 触发阈值
timestamp      # UTC 时间
resolved       # 指标恢复后标记为 true
```

同一个指标不会在每次采集时无限新增重复告警。指标恢复正常后，旧告警会被标记为
已恢复。

### `Suggestion`

保存可执行的优化建议：

```text
title          # 建议标题
detail         # 当前观察到的情况
action         # 下一步可以采取的操作
priority       # 1 到 10，数值越大越优先
```

当前建议主要覆盖 Tool 连续失败和 Agent 成功率持续偏低。它只提供建议，不会自动
修改 Prompt、Skill 或业务数据。

### `AnomalyDetector`

使用有上限的滑动窗口保存指标历史，并用 Z-score 判断当前值是否明显偏离近期水平。
样本不足时不触发异常，避免服务刚启动时产生没有意义的告警。

当前默认参数：

```text
window       = 60
sensitivity  = 2.5
```

这只是运行时异常检测，不等同于 Evaluation。它只能说明指标发生了异常，不能说明
模型回答内容是否正确。

### `PerformanceMonitor`

核心属性：

```text
orchestrator       # Agent 统计来源和路由反馈目标
tool_manager       # Tool 统计来源
interval_seconds   # 后台采集间隔
webhook_url        # 可选告警通知地址
detector           # AnomalyDetector
alerts             # 当前和历史告警
suggestions        # 去重后的优化建议
active             # Monitor 后台循环是否运行
```

核心方法：

```text
start()                  # 启动后台采集任务
stop()                   # 停止后台采集任务
collect_once()           # 手动采集一次，便于测试和排查
summary()                # 返回监控摘要
metrics_payload()        # 返回 Prometheus 文本格式指标
```

## 采集的 Agent 指标

`AgentOrchestrator.get_stats()` 现在按 Agent 实例返回数据。例如：

```text
technical_0:
  total
  success
  success_rate
  avg_ms
  monitor_penalty
  routing_score
  role
  workflow
  tool_scope
  model
```

其中：

```text
success_rate      # 成功请求数 / 总请求数
avg_ms            # 平均处理耗时
monitor_penalty   # Monitor 写回的 0 到 0.9 路由惩罚
routing_score     # Agent 当前用于选择的评分
```

为了兼容项目已有接口，同时保留了 `average_ms` 字段。Agent 名称使用
`general_0`、`technical_0` 这样的形式，便于未来同一类型下增加多个 Agent 实例。

## 采集的 Tool 指标

`ToolManager` 继续保存每个 Tool 的运行信息：

```text
total
success
failed
success_rate
avg_latency_ms
cache_hits
fallback_count
consecutive_fails
circuit_state
```

其中 `avg_latency_ms`、`consecutive_fails` 是 Monitor 统一使用的字段；已有的
`average_latency_ms`、`consecutive_failures` 仍然保留，避免破坏之前的接口。

## 阈值和路由反馈

当前阈值：

```text
Agent success rate < 0.90  → ERROR
Tool success rate  < 0.95  → WARNING
Agent average time > 3000ms → WARNING
Tool average time  > 5000ms → ERROR
```

Monitor 会把 Agent 的在线表现转换成有限的惩罚：

```text
成功率下降       → 增加惩罚
平均耗时过高     → 增加惩罚
惩罚最大为 0.9   → 避免完全删除 Agent
```

随后调用：

```text
PerformanceMonitor
→ AgentOrchestrator.update_routing_penalties()
→ AgentStats.monitor_penalty
→ routing_score()
→ _best_agent()
```

目前每种 Agent 只有一个实例，因此惩罚主要用于观测和后续扩展。未来同一领域存在
多个 Agent 实例时，路由器才会真正根据在线表现选择更可靠的实例。

## API 接口

### `GET /monitor`

返回：

```text
active
last_collection_at
prometheus_available
agent_stats
tool_stats
active_alerts
suggestions
```

它只读取内存中的统计，不调用大模型。

### `GET /metrics`

返回 Prometheus-compatible 文本指标，包括：

```text
arclume_agent_success_rate
arclume_agent_latency_ms
arclume_tool_success_rate
arclume_monitor_active
```

`prometheus-client` 会在安装后提供完整指标对象；即使本地没有安装该依赖，API 仍
会返回当前统计的基础文本，方便先进行开发测试。

### `/health`

健康检查现在额外报告：

```text
monitor.active
monitor.prometheus_available
```

## 启动和配置

```text
ARCLUME_MONITOR_ENABLED=true
ARCLUME_MONITOR_INTERVAL_SECONDS=10
ARCLUME_MONITOR_WEBHOOK_URL=
PROMETHEUS_PORT=0
```

默认情况下 Monitor 在 API 启动时运行，每 10 秒采集一次。`PROMETHEUS_PORT=0` 表示
不额外启动 Prometheus 端口，只通过 `/metrics` 暴露指标。

启动 API 后可以直接检查：

```bash
curl http://127.0.0.1:8000/monitor
curl http://127.0.0.1:8000/metrics
```

第一次刚启动时可能还没有 Agent 或 Tool 请求，统计值会保持默认状态；发送几次
请求后再次查看即可看到实际运行数据。

## 一次采集流程

```text
后台 Monitor 任务
→ 读取 Orchestrator.get_stats()
→ 读取 ToolManager.get_stats()
→ 检查成功率和延迟阈值
→ 更新异常检测窗口
→ 生成或恢复 Alert
→ 生成去重后的 Suggestion
→ 计算 Agent routing penalty
→ 写回 Orchestrator
→ 更新 /monitor 和 /metrics
```

这个过程和 `/chat` 请求并行运行，不会阻塞客服回答，也不会额外消耗模型 Token。

## 本步暂不实现

```text
根据监控结果自动修改 Skill
根据监控结果自动修改 Prompt
自动替换 Agent
自动发布优化方案
Evaluation 和 LLM Judge
```

这些行为需要等下一步 Evaluation 提供离线和在线质量判断后再考虑。Monitor 只负责
观察、告警和提供有限的路由反馈。

## 测试

```bash
./.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
./.venv/bin/python -m compileall -q api agents core harness knowledge memory monitor schemas tools tests
```

本步完成标准：

```text
PerformanceMonitor 可以独立启动和停止
可以读取 Agent 和 Tool 统计
可以检测阈值异常和连续失败
可以返回 Alert 和 Suggestion
可以把有限 penalty 写回 Orchestrator
可以通过 /monitor 查看摘要
可以通过 /metrics 查看基础指标
不增加客服请求中的模型调用
```
