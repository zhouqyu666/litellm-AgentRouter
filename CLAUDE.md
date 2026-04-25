# Claude Agent Playbook

- Start every task by clarifying expected tests and success criteria; draft the test list before touching implementation.
- Execute `_flake8.ps1` at the outset to understand current lint status; rerun after changes to ensure no regressions.
- Use `_autopep8.ps1` to auto-format prior to manual lint corrections, then rerun `_flake8.ps1` and resolve any remaining warnings.
- Keep overall coverage above 95% by writing targeted tests alongside code changes.
- Create empty `__init__.py` files in new Python packages/directories to ensure proper module recognition.
- Avoid `__all__` or explicit export statements at the end of Python files; rely on natural module structure.
- Use descriptive variable names that clearly indicate their purpose and data type (e.g., `user_id` instead of `uid`, `is_authenticated` instead of `auth`).
- Record assumptions, outstanding questions, and follow-up items so the next contributor (human or agent) has full context.
- Prefer using centralized config src\config\config.py instead of os.getenv
- Source code should follow SOLID principles

## 代码库概览

- Python 3.8+ 项目，使用 LiteLLM 作为核心依赖实现多模型代理功能。
- 代码已从单体模块重构为聚焦子系统（`config/`、`telemetry/`）。
- 测试覆盖率需保持 95% 以上。
- 项目在 Windows 上使用 PowerShell 脚本执行常见任务（`_flake8.ps1`、`_autopep8.ps1`、`_restart.ps1`）。

## 核心概念

- **Model Specs**: 定义在 `src/config/models.py`，描述模型能力（推理支持、参数过滤）。
- **Reasoning Effort**: 部分模型（DeepSeek、GPT-5）支持通过自定义参数控制推理强度。
- **Alias Lookup**: 遥测系统将模型别名解析为规范名称，确保日志一致性。
- **多模型配置**: 通过 `MODEL_<KEY>_*` 环境变量声明模型，自动发现（字母序排列），无需 `PROXY_MODEL_KEYS`（已忽略）。
- **多 Key 负载均衡**: 通过 `OPENAI_API_KEYS`（逗号分隔）或 `OPENAI_API_KEY`（含逗号时自动拆分）配置多个 API Key，LiteLLM 使用 `simple-shuffle` 策略在 Key 间轮询分发请求。
- **Node 上游代理**: agentrouter.org 拒绝非 Node.js SDK 客户端，所有上游请求必须通过 Node 代理转发。Node 代理通过 `ClientPool` 为每个 API Key 缓存独立的 OpenAI SDK 客户端实例。
- **动态 API Key 路由**: Node 代理从请求的 `Authorization` 头提取 Bearer Token 作为 API Key，不再使用固定配置的 Key。`buildForwardHeaders` 不转发来源请求的 `User-Agent`，确保上游始终看到 OpenAI SDK 的 User-Agent。
- **统一 OpenAI 兼容路由**: 所有模型（包括 Claude）统一通过 OpenAI 兼容路径（`/v1/chat/completions`）转发，不使用 Anthropic 原生 API。`models.py` 中的 `_PROVIDER_PATTERNS` 不再映射 `claude→anthropic`。
- **Master Key 环境变量**: `LITELLM_MASTER_KEY` 环境变量控制客户端认证，`parsing.py` 和 `cli.py` 均从该环境变量读取（有 `sk-local-master` 回退默认值）。

## 关键文件

- `src/config/rendering.py` — `render_config()` 生成 YAML 配置，`parse_api_keys()` 解析逗号分隔的 Key 列表
- `src/config/parsing.py` — `prepare_config()` 组装配置参数，处理多 Key 优先级逻辑
- `src/config/entrypoint.py` — Docker 容器入口，包含相同的多 Key 处理逻辑
- `src/cli.py` — CLI 参数解析，`--upstream-base` 默认为 `None`（不设置时走 Node 代理）
- `node/lib/client/client-pool.mjs` — `ClientPool` 按 API Key 缓存 OpenAI SDK 客户端
- `node/lib/router/router.mjs` — 提取 Bearer Token，动态解析 API Key
- `node/lib/router/routes.mjs` — 接受 `clientResolver` 函数动态创建客户端
- `node/lib/client/anthropic-client-pool.mjs` — `AnthropicClientPool` 按 API Key 缓存 Anthropic SDK 客户端（使用 `authToken` 发 Bearer 头）
- `node/lib/utils/http-utils.mjs` — `buildForwardHeaders` 仅转发 `X-Request-ID`，不转发 `User-Agent`
- `test_keys_and_loadbalance.py` — Key 验证和负载均衡测试脚本

## 修改注意事项

- 始终检查修改是否影响配置管线（env → CLI → YAML → proxy）。
- 考虑与现有 `.env` 文件和 CLI 使用模式的向后兼容性。
- 添加新模型或功能时，同时更新单元测试和集成测试。
- 确认生成的 YAML 配置中密钥使用 `os.environ/VAR_NAME` 引用（不硬编码）。
- 修改 Node 代理时，确保 `buildForwardHeaders` 不转发 `User-Agent`（agentrouter.org 会拒绝非 SDK 的 User-Agent）。
- 修改多 Key 逻辑时，注意优先级：`OPENAI_API_KEYS` > `OPENAI_API_KEY`（含逗号）> `OPENAI_API_KEY`（单 Key）。
- `--upstream-base` CLI 参数默认为 `None`，设置后会绕过 Node 代理直连上游（仅用于自定义端点）。
- 本地开发时 LiteLLM 和 Node 代理使用不同端口（`.env` 中 `PORT=8000`，Node 代理固定 `4000`），避免端口冲突。Docker 内部 LiteLLM 固定使用 `4000`（由 `entrypoint.py` 控制），不存在冲突。
- `master_key` 优先级：CLI `--master-key` > 环境变量 `LITELLM_MASTER_KEY` > 默认值 `sk-local-master`。
- 所有模型（包括 Claude）统一走 OpenAI 兼容路径（`openai/` provider），不要在 `models.py` 的 `_PROVIDER_PATTERNS` 中添加模型名到 provider 的映射。
