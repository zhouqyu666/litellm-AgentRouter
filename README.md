# LiteLLM AgentRouter

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Version](https://img.shields.io/badge/version-v1.0.0-green.svg)
![Python](https://img.shields.io/badge/Python-3.8+-3776AB.svg)
![Node.js](https://img.shields.io/badge/Node.js-20+-339933.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)

一个轻量级的 OpenAI 兼容 API 代理，基于 LiteLLM 实现多模型路由与多 API Key 负载均衡，通过 Node.js 上游代理解决 agentrouter.org 的客户端兼容性问题。

> 一个镜像，两个服务，多个模型，多把钥匙，一键启动。

---

## 项目介绍

### 概述

LiteLLM AgentRouter 是一个双层代理系统，为 agentrouter.org 等上游 API 提供 OpenAI 兼容的本地接入点。项目解决了两个核心问题：

1. **客户端兼容性** — agentrouter.org 拒绝非 Node.js SDK 的请求，Node.js 上游代理使用官方 `openai` SDK 转发所有上游流量
2. **多 Key 负载均衡** — 通过 LiteLLM 内置路由器在多个 API Key 之间轮询分发请求，单个 Key 失败时自动故障转移

### 核心功能

- 多模型路由：GPT-5、DeepSeek v3.2、Grok Code Fast-1、GLM-4.6 等
- 多 API Key 负载均衡：`simple-shuffle` 轮询策略 + 自动故障转移
- OpenAI 兼容接口：任何支持 OpenAI API 的客户端均可直接接入
- 推理强度控制：按模型配置 `none` / `low` / `medium` / `high`
- 请求遥测：结构化 JSON 日志，可插拔 Sink 架构
- 容器化部署：单镜像双服务，Docker Compose 一键启动

### 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.8+ | LiteLLM 代理、配置管线、中间件 |
| LiteLLM | 1.78.7 | 多模型代理核心、路由与负载均衡 |
| Node.js | 20+ | 上游代理、OpenAI SDK 客户端 |
| OpenAI SDK (JS) | ^6.8.1 | 官方 SDK，解决 User-Agent 兼容性 |
| Docker | - | 容器化部署与编排 |

---

## 功能清单

| 功能名称 | 功能说明 | 状态 |
|---------|---------|------|
| 多模型路由 | 通过 `MODEL_<KEY>_*` 环境变量自动发现并注册多个模型 | 已完成 |
| 多 Key 负载均衡 | 多个 API Key 轮询分发请求，单 Key 失败自动重试 | 已完成 |
| Node.js 上游代理 | 使用官方 OpenAI SDK 转发请求，解决 User-Agent 兼容性 | 已完成 |
| 动态 API Key 路由 | 从请求头提取 Bearer Token，按 Key 缓存 SDK 客户端 | 已完成 |
| 推理强度控制 | 按模型配置推理强度，不支持的模型自动过滤参数 | 已完成 |
| 流式响应 | 支持 SSE 流式输出，可按请求/全局开关 | 已完成 |
| 请求遥测 | 结构化 JSON 日志，Console / Logger / InMemory Sink | 已完成 |
| Docker 一键部署 | 单镜像双服务，Docker Compose 编排，健康检查 | 已完成 |

---

## 安装说明

### 环境要求

- Docker 20+ 和 Docker Compose V2（容器部署）
- 或 Python 3.8+ 和 Node.js 20+（源码部署）
- 至少一个 agentrouter.org 的 API Key

### Docker Compose 部署（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/zhouqyu666/litellm-AgentRouter.git
cd litellm-AgentRouter

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key 和模型配置

# 3. 启动服务（自动从 Docker Hub 拉取镜像）
docker-compose up -d

# 4. 查看日志确认启动成功
docker-compose logs -f
```

`litellm-proxy` 配置了 `depends_on` 等待 `node-proxy` 健康检查通过后才启动，无需手动控制启动顺序。

### 源码部署

```bash
# 1. 安装 Python 依赖
pip install -e ".[test]"

# 2. 安装 Node 依赖并启动 Node 代理（必须先启动）
cd node && npm install && cd ..
node node/main.mjs  # 监听端口 4000

# 3. 另开终端，启动 Python LiteLLM 代理
python3 -m src.main --port 8000  # 连接 Node 代理 localhost:4000

# 4. 运行测试
pytest
```

> **注意**: 源码部署时，Node 代理（端口 4000）和 Python 代理（端口 8000）必须同时运行。Node 代理必须先启动。

---

## 使用说明

### 快速开始

启动服务后，代理默认监听 `http://localhost:4000`，使用任何 OpenAI 兼容客户端即可接入：

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-local-master",       # Master Key（见 .env 中的 LITELLM_MASTER_KEY）
    base_url="http://localhost:4000"  # 代理地址
)

response = client.chat.completions.create(
    model="gpt-5",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

### 配置说明

所有配置通过 `.env` 文件中的环境变量完成，参见 `.env.example`。

#### 核心配置

```bash
PORT=4000                          # 代理端口（默认: 4000）
LITELLM_MASTER_KEY=sk-local-master # 客户端认证 Master Key
STREAMING_ENABLE=true              # 启用流式响应（默认: true）
TELEMETRY_ENABLE=1                 # 启用遥测日志（默认: 1）
```

#### 上游 API 配置

```bash
OPENAI_BASE_URL=https://agentrouter.org/v1  # 上游 API 地址
OPENAI_API_KEY=your-api-key                  # 单个 API Key
MAX_TOKENS=8192                              # 最大 Token 数
REASONING_EFFORT=medium                      # 默认推理强度（none/low/medium/high）
```

#### 多 API Key 负载均衡

支持多个 API Key 轮询负载均衡。配置后，每个模型会为每个 Key 生成一个独立的 LiteLLM 路由条目，使用 `simple-shuffle` 策略轮询分发请求。

```bash
# 方式一（推荐）：使用 OPENAI_API_KEYS（逗号分隔）
OPENAI_API_KEYS=sk-key1,sk-key2,sk-key3

# 方式二：在 OPENAI_API_KEY 中用逗号分隔（自动识别）
OPENAI_API_KEY=sk-key1,sk-key2,sk-key3
```

**优先级**: `OPENAI_API_KEYS` > `OPENAI_API_KEY`（含逗号时自动拆分）> `OPENAI_API_KEY`（单 Key）

**工作原理**:
- LiteLLM 为每个 Key 生成独立的模型路由条目
- 使用 `simple-shuffle` 路由策略在多个 Key 间轮询
- Node 代理通过 `ClientPool` 为每个 Key 缓存独立的 OpenAI SDK 客户端
- 某个 Key 请求失败时（如 401），LiteLLM 自动使用下一个 Key 重试

#### 多模型配置

通过 `MODEL_<KEY>_*` 环境变量声明模型，自动发现并加载（按字母顺序排序）：

```bash
# GPT-5 配置
MODEL_GPT5_UPSTREAM_MODEL=gpt-5
MODEL_GPT5_REASONING_EFFORT=medium

# DeepSeek v3.2 配置
MODEL_DEEPSEEK_UPSTREAM_MODEL=deepseek-v3.2
MODEL_DEEPSEEK_REASONING_EFFORT=medium

# Grok Code Fast-1 配置
MODEL_GROK_UPSTREAM_MODEL=grok-code-fast-1
MODEL_GROK_REASONING_EFFORT=high

# GLM-4.6 配置（不支持 reasoning_effort）
MODEL_GLM_UPSTREAM_MODEL=glm-4.6
```

#### 单模型配置

至少设置一个 `MODEL_<KEY>_UPSTREAM_MODEL` 变量即可：

```bash
MODEL_PRIMARY_UPSTREAM_MODEL=gpt-5
MODEL_PRIMARY_REASONING_EFFORT=medium
```

#### 模型级覆盖

每个模型可覆盖全局设置：

```bash
MODEL_GPT5_UPSTREAM_BASE=https://custom-endpoint.com/v1  # 覆盖上游地址
MODEL_DEEPSEEK_REASONING_EFFORT=high                      # 覆盖推理强度
```

> **注意:** `PROXY_MODEL_KEYS` 已被忽略（存在时会输出警告），请从 `.env` 中移除。

### 使用示例

#### Python OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(api_key="sk-local-master", base_url="http://localhost:4000")

# 使用 GPT-5
response = client.chat.completions.create(
    model="gpt-5",
    messages=[{"role": "user", "content": "用 Python 写一个快速排序"}]
)

# 使用 GLM-4.6
response = client.chat.completions.create(
    model="glm-4.6",
    messages=[{"role": "user", "content": "你好"}]
)
```

#### cURL

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-local-master" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

#### Droid CLI

在 `~/.factory/config.json` 中配置:

```json
{
  "model_display_name": "ChatGPT 5 (AgentRouter - local proxy)",
  "model": "gpt-5",
  "base_url": "http://localhost:4000",
  "api_key": "sk-local-master",
  "provider": "generic-chat-completion-api",
  "max_tokens": 8192
}
```

---

## 项目结构

```
litellm-AgentRouter/
├── src/                               # Python 主应用
│   ├── main.py                        # 入口：启动消息、配置准备、信号处理
│   ├── cli.py                         # CLI 参数解析
│   ├── proxy.py                       # 代理启动 & LiteLLM 集成
│   ├── utils.py                       # 工具函数
│   ├── config/                        # 配置子系统
│   │   ├── config.py                  # RuntimeConfig 集中配置对象
│   │   ├── models.py                  # ModelSpec 模型能力定义
│   │   ├── parsing.py                 # 环境变量解析 & 多模型发现
│   │   ├── rendering.py               # YAML 配置生成 & 多 Key 渲染
│   │   └── entrypoint.py             # Docker 容器入口逻辑
│   ├── middleware/                     # 中间件子系统
│   │   ├── registry.py                # 中间件注册
│   │   ├── reasoning_filter/          # 推理参数过滤中间件
│   │   └── telemetry/                 # 遥测中间件 & Sink 架构
│   └── node/
│       └── process.py                 # Node.js 子进程管理
│
├── node/                              # Node.js 上游代理
│   ├── main.mjs                       # 入口：服务启动 & 信号处理
│   └── lib/
│       ├── client/
│       │   ├── client.mjs             # OpenAI SDK 客户端封装
│       │   └── client-pool.mjs        # ClientPool：按 Key 缓存客户端
│       ├── config/
│       │   ├── config.mjs             # NodeProxyConfig 配置类
│       │   └── constants.mjs          # 默认常量
│       ├── router/
│       │   ├── router.mjs             # HTTP 请求路由 & Bearer Token 提取
│       │   └── routes.mjs             # 路由定义 & 动态客户端解析
│       ├── server/
│       │   ├── server.mjs             # NodeProxyServer 服务类
│       │   └── proxy.mjs              # 代理工厂函数
│       └── utils/
│           ├── http-utils.mjs         # HTTP 工具（仅转发 X-Request-ID）
│           └── logger.mjs             # JSON 日志工具
│
├── tests/                             # 测试套件（136 个文件）
│   ├── unit/                          # 单元测试
│   └── integration/                   # 集成测试
│
├── specs/                             # 产品需求文档（13 个）
├── Dockerfile                         # 镜像构建（Python + Node.js）
├── docker-compose.yml                 # 容器编排
├── entrypoint.sh                      # Docker 入口脚本
├── test_keys_and_loadbalance.py       # Key 验证 & 负载均衡测试脚本
├── .env.example                       # 环境变量模板
├── pyproject.toml                     # Python 项目配置
└── package.json                       # Node.js 项目配置
```

---

## 架构

### 请求流转路径

```
客户端请求
    │
    ▼
┌─────────────────────────────────────┐
│  LiteLLM Python 代理                 │
│  (端口 4000 / 8000)                  │
│                                      │
│  - 客户端认证（Master Key）          │
│  - 模型路由（根据 model 参数）       │
│  - 负载均衡（多 Key 轮询）           │
│  - 推理参数过滤                      │
│  - 请求遥测日志                      │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Node.js 上游代理                    │
│  (端口 4000)                         │
│                                      │
│  - 提取 Bearer Token 作为 API Key    │
│  - ClientPool 按 Key 缓存 SDK 客户端│
│  - 使用 OpenAI SDK 正确 User-Agent   │
│  - 支持流式 / 非流式响应             │
└──────────────┬──────────────────────┘
               │
               ▼
        agentrouter.org
```

### Docker 网络架构

```
┌─────────────────────────────────────────────────────────┐
│                   Docker 网络 (litellm-network)          │
│                                                          │
│  ┌──────────────────┐       ┌──────────────────┐       │
│  │   node-proxy     │       │  litellm-proxy   │       │
│  │   Node.js 20     │◄──────│  Python 3.12     │       │
│  │   端口: 4000     │       │  端口: 4000      │       │
│  │   （仅内部访问） │       │  （对外暴露）    │       │
│  └────────┬─────────┘       └──────────────────┘       │
│           │                                              │
└───────────┼──────────────────────────────────────────────┘
            │
            ▼
     agentrouter.org
```

---

## 部署

### Docker 镜像

预构建镜像已发布到 Docker Hub：

```
wwwzhouhui569/litellm-agentrouter:latest
```

该镜像同时包含 Python 和 Node.js 运行时，`docker-compose.yml` 通过不同的启动命令区分两个服务：
- **node-proxy**: `node /app/node/main.mjs`（Node 上游代理）
- **litellm-proxy**: `/app/entrypoint.sh`（LiteLLM Python 代理）

### Docker Compose 常用命令

```bash
# 启动服务（从 Docker Hub 拉取预构建镜像）
docker-compose up -d

# 停止服务
docker-compose down

# 查看所有日志
docker-compose logs -f

# 查看单个服务日志
docker-compose logs -f node-proxy
docker-compose logs -f litellm-proxy

# 更新到最新镜像
docker-compose pull && docker-compose up -d
```

### 构建 Docker 镜像

如果需要自行构建镜像（例如修改代码后重新打包）：

```bash
# 构建镜像
docker build -t wwwzhouhui569/litellm-agentrouter .

# 推送到 Docker Hub（需先 docker login）
docker push wwwzhouhui569/litellm-agentrouter
```

镜像基于 `python:3.12-slim`，额外安装了 Node.js 运行时，同时包含 Python 和 Node.js 两套代码。两个服务共用同一个镜像，通过 `docker-compose.yml` 中不同的 `command` / `entrypoint` 启动不同的服务进程。

### 容器单独启动

不使用 docker-compose 时，可手动启动容器：

```bash
# 创建网络
docker network create litellm-network

# 启动 Node 上游代理
docker run -d \
  --name litellm-node-proxy \
  --network litellm-network \
  --env-file .env \
  --restart unless-stopped \
  wwwzhouhui569/litellm-agentrouter:latest \
  node /app/node/main.mjs

# 启动 LiteLLM Python 代理
docker run -d \
  --name litellm-python-proxy \
  --network litellm-network \
  --env-file .env \
  -p 4000:4000 \
  --entrypoint /bin/bash \
  --restart unless-stopped \
  wwwzhouhui569/litellm-agentrouter:latest \
  /app/entrypoint.sh
```

---

## 开发指南

### 本地开发

```bash
# 安装 Python 依赖（含测试依赖）
pip install -e ".[test]"

# 安装 Node 依赖
cd node && npm install && cd ..

# 启动 Node 代理（终端 1）
node node/main.mjs

# 启动 Python 代理（终端 2）
python3 -m src.main --port 8000

# 运行 Python 测试
pytest

# 运行 Node 测试
npm test
```

### 代码风格

- Python: `flake8` 检查 + `autopep8` 格式化
- 测试覆盖率目标: 95%+
- 遵循 SOLID 原则

### 测试脚本

提供 `test_keys_and_loadbalance.py` 脚本用于验证 API Key 有效性和负载均衡效果：

```bash
# 验证每个 Key（需先启动 Node 代理）
python3 test_keys_and_loadbalance.py --direct --keys "sk-key1,sk-key2,sk-key3"

# 测试负载均衡（需同时启动 Node 代理和 LiteLLM 代理）
python3 test_keys_and_loadbalance.py --proxy

# 同时测试两者
python3 test_keys_and_loadbalance.py --direct --proxy --keys "sk-key1,sk-key2,sk-key3"

# 自定义参数
python3 test_keys_and_loadbalance.py --direct --proxy \
    --keys "sk-key1,sk-key2" \
    --model glm-4.6 \
    --proxy-url http://localhost:8000 \
    --node-proxy-url http://localhost:4000/v1 \
    --timeout 120 \
    --rounds 9
```

**参数说明**:

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--direct` | 通过 Node 代理逐个验证每个 API Key 的有效性 | - |
| `--proxy` | 通过 LiteLLM 代理测试负载均衡效果 | - |
| `--keys` | 逗号分隔的 API Key 列表 | 从 `.env` 读取 |
| `--model` | 测试模型名称 | `glm-4.6` |
| `--node-proxy-url` | Node 代理地址 | `http://localhost:4000/v1` |
| `--proxy-url` | LiteLLM 代理地址 | `http://localhost:8000` |
| `--timeout` | 单次请求超时秒数 | `120` |
| `--rounds` | 负载均衡测试轮次 | `6` |

### 贡献指南

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/xxx`)
3. 提交变更 (`git commit -m 'Add xxx'`)
4. 推送分支 (`git push origin feature/xxx`)
5. 创建 Pull Request

---

## 常见问题

<details>
<summary>启动后请求返回 "unauthorized client detected" 怎么办？</summary>

这表示请求绕过了 Node 代理直接到达 agentrouter.org。请确认：
1. Node 代理已启动并监听端口 4000
2. 环境变量 `NODE_UPSTREAM_PROXY_ENABLE=1`
3. 未设置 `--upstream-base` CLI 参数（设置后会绕过 Node 代理）

</details>

<details>
<summary>多个 API Key 只有部分生效？</summary>

1. 使用 `test_keys_and_loadbalance.py --direct` 逐个验证 Key 有效性
2. 确认使用 `OPENAI_API_KEYS`（复数）环境变量，逗号分隔
3. 如果使用 `OPENAI_API_KEY`（单数），确保包含逗号才会自动拆分

</details>

<details>
<summary>请求超时（timed out）怎么办？</summary>

agentrouter.org 首次请求可能有冷启动延迟（30 秒以上）。解决方法：
1. 测试脚本默认超时已设为 120 秒
2. 可通过 `--timeout 180` 增加超时时间
3. 后续请求通常会明显加快

</details>

<details>
<summary>Docker Compose 启动后 litellm-proxy 一直重启？</summary>

`litellm-proxy` 依赖 `node-proxy` 健康检查通过后才启动。如果 `node-proxy` 健康检查失败：
1. 检查 `docker-compose logs node-proxy` 的错误日志
2. 确认 `.env` 文件存在且格式正确
3. 确认网络 `litellm-network` 正常创建

</details>

<details>
<summary>PROXY_MODEL_KEYS 环境变量还需要吗？</summary>

不需要。`PROXY_MODEL_KEYS` 已被弃用并忽略（存在时会输出警告）。现在通过 `MODEL_<KEY>_UPSTREAM_MODEL` 环境变量自动发现模型，无需额外声明 Key 列表。

</details>

---

## 项目统计

### 代码统计

| 类型 | 文件数 | 说明 |
|------|--------|------|
| Python 源码 | 66 | 主应用、配置、中间件、遥测 |
| Node.js 源码 | 22 | 上游代理、客户端池、路由 |
| 测试文件 | 136 | 单元测试 + 集成测试，覆盖率 95%+ |
| 需求文档 | 13 | PRD 设计文档（specs/） |

### 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0.0 | 2025 | 初始版本：多模型代理、Node 上游转发、遥测中间件 |
| v1.1.0 | 2026-02 | 多 API Key 负载均衡、动态 Key 路由、ClientPool、测试脚本 |

---

## 路线图

### 计划功能

- [ ] Web 管理面板：可视化查看请求日志和 Key 用量
- [ ] Key 用量统计：按 Key 统计请求数、Token 消耗
- [ ] 权重路由：支持按 Key 配置不同的分发权重
- [ ] 自动 Key 禁用：连续失败超过阈值自动移除 Key

### 优化项

- [ ] 镜像体积优化：拆分 Python / Node.js 为独立镜像
- [ ] 连接池预热：启动时预创建 SDK 客户端
- [ ] 请求重试策略：可配置重试次数和退避策略

---

## 技术交流群

欢迎加入技术交流群，分享你的使用心得和建议：

![微信群二维码](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/Obsidian/%25E5%25BE%25AE%25E4%25BF%25A1%25E5%259B%25BE%25E7%2589%2587_20260223133201_158_292.jpg)

---

## 作者联系

- **微信**: laohaibao2025
- **邮箱**: 75271002@qq.com

![微信二维码](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/Screenshot_20260123_095617_com.tencent.mm.jpg)

---

## 打赏

如果这个项目对你有帮助，欢迎请我喝杯咖啡 ☕

**微信支付**

![微信支付](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/Obsidian/image-20250914152855543.png)

---

## License

SPDX-License-Identifier: MIT

本项目基于 MIT 协议开源，详见 [LICENSE](LICENSE) 文件。

---

## Star History

如果觉得项目不错，欢迎点个 Star

[![Star History Chart](https://api.star-history.com/svg?repos=zhouqyu666/litellm-AgentRouter&type=Date)](https://star-history.com/#zhouqyu666/litellm-AgentRouter&Date)
