# 第八步：加入静态 Skills

## 当前项目目录

```text
arclume/
├── api/
│   ├── __init__.py                 # Python 包声明
│   └── main.py                    # FastAPI 入口和资源初始化
├── agents/
│   ├── __init__.py                 # Python 包声明
│   └── customer_service_agent.py  # 单 Agent 客服逻辑
├── core/
│   ├── __init__.py                 # Python 包声明
│   ├── llm_utils.py               # 大模型 HTTP 调用
│   ├── context_builder.py         # 组装一次模型请求的 Context
│   └── skill_loader.py             # 读取静态 Skill 文件
├── harness/
│   ├── __init__.py                 # Python 包声明
│   ├── policy.py                  # Tool 权限和风险判断
│   ├── executor.py                # Tool 执行和结果统一
│   ├── trace.py                   # Harness 事件记录
│   └── runtime.py                 # Harness 运行控制和最小循环
├── knowledge/
│   ├── __init__.py                # 知识库异常类型
│   └── knowledge_base.py          # ChromaDB 文档入库和检索
├── memory/
│   ├── __init__.py                 # MemoryStoreError
│   ├── conversation_memory.py     # Redis 短期对话记忆
│   └── state_store.py             # Redis AgentState 保存
├── schemas/
│   ├── __init__.py                 # Python 包声明
│   ├── api.py                     # API 请求和响应模型
│   ├── state.py                   # AgentState 模型
│   ├── context.py                 # Context 模型
│   └── tool.py                    # ToolCall 和 ToolResult 模型
├── skills/
│   ├── refund/
│   │   └── SKILL.md               # 退款处理规范
│   ├── logistics/
│   │   └── SKILL.md               # 物流处理规范
│   └── escalation/
│       └── SKILL.md               # 转人工规范
├── data/
│   └── demo_docs/                 # RAG 演示知识文档
├── docs/
│   ├── step1.md                  # 第一步记录
│   ├── step2.md                  # 第二步记录
│   ├── step3.md                  # 第三步记录
│   ├── step4.md                  # 第四步记录
│   ├── step5.md                  # 第五步记录
│   ├── step6.md                  # 第六步记录
│   ├── step7.md                  # 第七步记录
│   └── step8.md                  # 第八步记录
├── .env.example                  # 环境变量模板
├── .gitignore                    # Git 忽略规则
├── .dockerignore                 # Docker 构建忽略规则
├── Dockerfile                    # 应用镜像描述，暂不测试
├── docker-compose.yml             # API、Redis 和 ChromaDB 服务编排
├── requirements.txt              # Python 依赖
└── README.md                     # 项目说明
```

## 本步目标

第七步已经可以把知识库检索结果放入 Context，但知识库解决的是“事实依据”
问题，不负责规定 Agent 应该怎样处理一个业务类型。

本步加入静态 Skill：由人工编写一组业务处理规范，运行时只读取，不自动修改。

```text
Skill 文件
  → SkillLoader 读取
  → 由上层选择需要的 Skill
  → Skill 指令放入 Context.skill_instructions
  → 模型按照业务规范回答
```

这里要区分两种内容：

```text
知识库：退款政策、配送时间等事实性内容
Skill：遇到退款问题时应该如何处理、需要注意什么、什么时候转人工
```

## 本步只做什么

```text
完成：Skill 文件目录和内容格式
完成：只读 SkillLoader
完成：Skill 内容接入 ContextBuilder
完成：Agent 支持显式传入 Skill 名称
完成：API 启动时发现可用 Skill
```

## 本步不做什么

```text
暂不做：自动意图识别
暂不做：根据用户消息自动选择 Skill
暂不做：多 Agent 路由
暂不做：Skill 自动生成、合并、修改或删除
暂不做：Skill 自进化和人工审批
```

当前 Agent 只有在收到明确的 `skill_names`，或者启动时配置了默认 Skill，
才会读取对应文件。API 当前没有把 Skill 名称开放给外部用户，也不会把全部
Skill 一起塞进每次请求。后面由 IntentRecognizer 和 Router 决定当前请求使
用哪个 Skill。

## 一次请求的运行流程

当前如果没有选择 Skill：

```text
API
  → CustomerServiceAgent
  → Memory / AgentState
  → KnowledgeBase 检索
  → ContextBuilder
  → LLMClient
```

如果上层显式选择了 `refund`：

```text
1. Agent 收到 skill_names=["refund"]
2. SkillLoader 读取 skills/refund/SKILL.md
3. SkillLoader 返回 SkillDocument
4. Agent 将 Skill 内容转换成 skill_instructions
5. ContextBuilder.build() 保存 Skill 指令
6. ContextBuilder.render_history() 把 Skill 放入模型 history
7. LLMClient 将 Skill、知识结果、历史消息和当前问题发送给模型
```

模型看到的结构大致是：

```text
system prompt
  ↓
AgentState
  ↓
Active Skill
  ↓
Relevant knowledge
  ↓
Conversation history
  ↓
Current user message
```

## `core/skill_loader.py`

### 文件作用

负责从指定的 `skills/` 目录读取人工编写的 `SKILL.md`，不负责判断用户意
图，不负责调用模型，也不负责修改文件。

### 类：`SkillDocument`

这是一个不可变的数据对象。

```text
name：Skill 名称，例如 refund
content：SKILL.md 的完整内容
path：文件实际路径，用于日志和排查
```

### 类：`SkillLoader`

核心属性：

```text
skills_dir：Skill 根目录，默认是 skills/
```

核心方法：

```text
from_environment()：从 ARCLUME_SKILLS_DIR 创建 Loader
list_available()：列出当前存在且格式正确的 Skill
load()：读取一个 Skill 文件
load_many()：按照指定顺序读取多个 Skill
_validate_name()：拒绝路径穿越和非法名称
```

依赖：Python 标准库、`SKILL.md` 文件。

被谁调用：

```text
api/main.py：启动时创建 SkillLoader，并在 /health 展示可用 Skill
agents/customer_service_agent.py：收到明确 Skill 名称时读取内容
```

### Skill 名称规则

为了防止传入 `../` 等路径，Skill 名称只允许：

```text
字母、数字、下划线、短横线
```

例如：

```text
refund
logistics
escalation
```

不允许直接传入任意文件路径。SkillLoader 只读取固定目录下的
`<skill_name>/SKILL.md`。

## 三个静态 Skill

### `skills/refund/SKILL.md`

规定退款问题的基本流程：

```text
判断退款类型
→ 查询政策
→ 必要时获取订单号
→ 不得虚构退款批准结果
→ 高风险操作需要 Tool 或人工审批
```

### `skills/logistics/SKILL.md`

规定物流问题的基本流程：

```text
区分通用配送政策和具体订单查询
→ 必要时获取订单号或物流单号
→ 不得虚构物流事件或送达日期
→ 异常情况转人工
```

### `skills/escalation/SKILL.md`

规定转人工时应该：

```text
说明转人工原因
→ 总结已经发生的事情
→ 保留案件状态
→ 只有在 Ticket Tool 成功后才能声称工单已创建
```

## `agents/customer_service_agent.py` 的变化

新增属性：

```text
skill_loader：读取静态 Skill 的 SkillLoader
default_skill_names：可选的默认 Skill 名称列表
```

`respond()` 新增参数：

```text
skill_names：本次请求明确指定的 Skill 名称列表
```

优先级是：

```text
本次 respond(skill_names=...) 的参数
  > default_skill_names
  > 不加载 Skill
```

读取之后，Agent 会把内容转换成：

```text
[Skill: refund]
<SKILL.md 的内容>
```

然后传给 `ContextBuilder.build(skill_instructions=...)`。

如果 Skill 文件不存在或格式错误，当前 Agent 会记录 warning，并继续使用
基础客服逻辑。这是因为 Skill 属于增强指导，不能让基础客服链路完全停止。

## `api/main.py` 的变化

应用启动时新增：

```text
SkillLoader.from_environment()
  → app.state.skill_loader
  → CustomerServiceAgent(skill_loader=...)
```

`GET /health` 现在会显示发现的 Skill 名称，例如：

```json
{
  "skills": ["escalation", "logistics", "refund"]
}
```

这里的 `skills` 只是表示文件存在，并不代表本次请求已经启用了这些 Skill。

## 为什么现在不自动选择 Skill

如果现在直接用关键词判断：

```text
出现 refund → 使用 refund Skill
出现 shipping → 使用 logistics Skill
```

会把意图识别逻辑提前塞进 Agent，而且以后还需要重新替换。

当前先让 SkillLoader 负责“读取”，让后面的 IntentRecognizer 和 Router 负责：

```text
判断用户意图
→ 决定是否需要 RAG
→ 决定使用哪个 Skill
→ 决定交给哪个 Agent
```

这样每个模块职责更清楚。

## 配置

`.env.example` 新增：

```text
ARCLUME_SKILLS_DIR=./skills
```

Dockerfile 会把 `skills/` 复制到应用镜像中。Skill 文件当前属于代码和配置
的一部分，应该经过 Git review 后才能生效；运行中的 Agent 不会自己改写它们。

## 测试方式

不需要调用真实模型 API。可以先检查 API 是否发现 Skill：

```bash
source .venv/bin/activate
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

另开终端：

```bash
curl http://127.0.0.1:8000/health
```

也可以使用一个假的模型和明确的 Skill 名称测试 Agent 内部流程。测试应该
确认模型收到的 history 中包含：

```text
[Skill: refund]
Refund Handling Skill 的内容
```

## 本步完成标准

```text
完成：Skill 文件可以按目录组织
完成：SkillLoader 只读取合法的 SKILL.md
完成：非法路径名称会被拒绝
完成：Skill 可以进入 Context.skill_instructions
完成：Agent 可以显式接收 Skill 名称
完成：没有调用真实模型也可以测试
暂不完成：自动 Skill 路由和 Skill 自进化
```
