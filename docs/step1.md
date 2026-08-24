# 第一步：建立项目骨架并启动基础服务

## 目标

先把 Arclume 的最小运行基础搭起来，确认 Python、FastAPI 和模型接口的本地运行方式没有问题。

这一阶段不设计复杂 Agent，不加入 memory、state、context、tools、skills 或自进化逻辑。Docker 文件先保留，后续再安装和验证。

## 本步完成内容

- 使用项目内的 Python 3.10 虚拟环境。
- 建立 `api/` 和 `core/` 基础代码目录。
- 完成 FastAPI 入口、请求模型和健康检查接口。
- 完成一个不绑定具体厂商的模型调用客户端。
- 创建依赖清单和环境变量模板。
- 预留 Redis、ChromaDB 的 Docker 服务位置，但暂时不接入业务逻辑。

## 主要文件

```text
api/main.py          # HTTP 入口、/health、/chat
core/llm_utils.py    # 模型接口调用
requirements.txt     # Python 依赖
.env.example         # 配置模板
Dockerfile           # 应用镜像描述
docker-compose.yml   # 服务编排描述
README.md            # 项目说明
```

## 整体设计概要

第一步只建立一条最小运行链路：

```text
客户端
  -> Uvicorn
  -> FastAPI
  -> Pydantic 校验请求
  -> LLMClient
  -> 外部模型 API
  -> FastAPI 返回 JSON
```

当前的核心关系：

```text
api/main.py
  -> core/llm_utils.py
  -> httpx
  -> 外部模型 API
```

这一阶段的 `/chat` 只是直接调用模型，还不是完整 Agent 流程。`conversation_id` 目前只是请求中的会话标识，不会保存历史消息；`app.state.llm` 只是保存模型客户端，也不是对话 State。

## 整体依赖关系

这里的“依赖”指的是一个文件或类要正常工作，需要使用哪些其他类、库或外部服务。

```text
项目内部依赖：api/main.py、LLMClient、LLMSettings
第三方库依赖：FastAPI、Pydantic、httpx、python-dotenv
外部服务依赖：模型 API
```

例如：

```text
api/main.py 依赖 LLMClient
LLMClient 依赖 LLMSettings 和 httpx
LLMClient 依赖外部模型 API
```

## 其他文件简单说明

这些文件本阶段只需要知道用途，不需要逐个展开类和方法：

```text
api/__init__.py       # 声明 api 是 Python 包
core/__init__.py      # 声明 core 是 Python 包
requirements.txt      # 记录需要安装的第三方包
.env.example          # 提供模型配置字段示例，不保存真实密钥
README.md             # 记录项目用途和启动方式
.gitignore            # 忽略虚拟环境、密钥和缓存文件
.dockerignore         # Docker 构建时忽略无关文件
Dockerfile            # 描述应用镜像如何构建和启动
docker-compose.yml    # 预留 API、Redis、ChromaDB 的服务关系
docs/step1.md         # 记录本阶段的计划和结构
```

Docker 相关文件先保留，不在本阶段安装、启动或验证 Docker。

## 按文件详细说明

### 文件：`api/main.py`

#### 文件作用

这是 HTTP 服务入口，负责接收外部请求，并把请求交给内部模块处理。

#### 主要职责

1. 创建 FastAPI 应用。
2. 读取环境变量配置。
3. 创建和关闭共享的模型客户端。
4. 定义 `/health` 和 `/chat` 接口。
5. 处理请求校验、模型结果和 HTTP 错误。

#### 模块级对象：`app`

```text
作用：FastAPI 应用对象
被谁使用：Uvicorn
用途：注册路由、管理应用生命周期、启动 HTTP 服务
```

#### 类：`ChatRequest`

```text
职责：定义 /chat 接收的数据格式

核心属性：
- message：用户消息
- conversation_id：会话标识

核心方法：无业务方法，由 Pydantic 自动校验

依赖：Pydantic BaseModel、Field
被谁使用：chat()
```

#### 类：`ChatResponse`

```text
职责：定义 /chat 返回的数据格式

核心属性：
- message：模型回复
- model：模型名称
- conversation_id：会话标识

核心方法：无业务方法

依赖：Pydantic BaseModel
被谁使用：chat()、FastAPI 响应校验
```

#### 同层函数：`lifespan()`

```text
类型：异步函数
作用：管理 FastAPI 应用的启动和关闭

启动时：调用 LLMClient.from_environment()
运行期间：把 LLMClient 保存到 app.state.llm
关闭时：调用 LLMClient.close()
```

#### 同层函数：`health()`

```text
类型：异步函数
作用：返回 API 和模型配置状态
调用：读取 app.state.llm.is_configured
被谁调用：FastAPI 的 GET /health 路由
```

#### 同层函数：`chat()`

```text
类型：异步函数
作用：接收用户消息并返回模型回复
输入：ChatRequest
调用：LLMClient.chat()
输出：ChatResponse
被谁调用：FastAPI 的 POST /chat 路由
```

#### 文件依赖

```text
FastAPI
Pydantic
python-dotenv
core/llm_utils.py
```

#### 调用关系

```text
Uvicorn
  -> FastAPI app
  -> lifespan()、health()、chat()
  -> LLMClient
  -> 外部模型 API
```

#### 一次 `/chat` 请求

```text
用户发送 JSON
  -> FastAPI 找到 chat()
  -> ChatRequest 校验 message
  -> chat() 调用 LLMClient.chat()
  -> LLMClient 请求模型服务
  -> chat() 创建 ChatResponse
  -> FastAPI 返回 JSON
```

---

### 文件：`core/llm_utils.py`

#### 文件作用

负责读取模型配置、创建模型客户端、发送 HTTP 请求、解析模型回复和统一处理模型错误。

#### 类：`LLMConfigurationError`

```text
职责：表示模型配置不完整或缺失
属性：使用异常默认属性
方法：使用异常默认方法
依赖：Python RuntimeError
被谁处理：api/main.py 的 chat()
```

#### 类：`LLMRequestError`

```text
职责：表示模型请求失败或返回格式错误
属性：使用异常默认属性
方法：使用异常默认方法
依赖：Python RuntimeError
被谁处理：api/main.py 的 chat()
```

#### 类：`LLMSettings`

```text
职责：保存模型服务配置

核心属性：
- provider：服务商标签
- api_key：API 密钥
- base_url：模型 API 地址
- model：模型名称
- timeout_seconds：请求超时时间

核心方法：
- from_environment()：从环境变量创建配置
- is_configured：判断配置是否完整

依赖：os、环境变量
被谁使用：LLMClient
```

#### 类：`LLMClient`

```text
职责：调用外部大模型 API

核心属性：
- settings：LLMSettings，保存模型配置
- _http：httpx.AsyncClient，发送异步 HTTP 请求

核心方法：
- from_environment()：从环境变量创建客户端
- is_configured：判断客户端是否可以调用模型
- chat()（异步）：发送一次模型请求
- close()（异步）：关闭 HTTP 连接

依赖：LLMSettings、httpx、外部模型 API
被谁调用：api/main.py 的 lifespan() 和 chat()
```

#### 同层函数

```text
无。
```

`from_environment()`、`is_configured()`、`chat()` 和 `close()` 都属于类内部方法，不是文件顶层函数。

#### 调用关系

```text
.env / 系统环境变量
  -> LLMSettings
  -> LLMClient
  -> httpx.AsyncClient
  -> 外部模型 API
```

## 执行顺序

1. 激活 `.venv`。
2. 安装 `requirements.txt` 中的依赖。
3. 从 `.env.example` 创建 `.env`，填写模型服务配置。
4. 本地启动 FastAPI，确认 `/docs` 和 `/health` 正常。
5. Docker 文件暂时只保留，不安装 Docker，也不启动容器。
6. 确认本地 API 正常后，再进入下一步。

## 终端测试

先在第一个终端启动服务：

```bash
source .venv/bin/activate
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

再打开第二个终端，执行健康检查：

```bash
curl -i http://127.0.0.1:8000/health
```

看到下面内容就说明 FastAPI 已经启动：

```text
HTTP/1.1 200 OK
```

这个测试不会调用大模型，也不会消耗 API Token。

## 完成标准

- FastAPI 可以启动。
- `/health` 可以返回服务状态。
- `/docs` 可以打开。
- `api/main.py` 和 `core/llm_utils.py` 的调用关系已经明确。
- Docker 配置文件已经预留，后续再单独验证。

## 本步暂不处理

Agent 编排、对话记忆、知识库检索、客服 Skill、工具调用、监控评测和自进化功能留到后续步骤。先确认最小运行链路稳定，再逐层增加能力。
