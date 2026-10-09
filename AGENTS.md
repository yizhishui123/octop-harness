# AGENTS.md

`octop-harness` 仓库的 AI 编码代理(Agent)工作手册。

> 本文件是**如何修改本仓库**的说明。`src/octop_harness/builtin/md_files/AGENTS.md`(随库发布、并复制到终端用户工作区)是**如何使用本库创建的 agent** 的说明。两者不是同一份文档——不要混淆。

## 1. 协作原则

> 谨慎优先于速度;琐碎任务可适当放宽。本节与 [§12 变更流程](#12-变更流程)、[§13 沟通规范](#13-沟通规范)互为补充。

### 先想后写

- 先读:要改动文件的 docstring、相邻实现、相关规格说明。
- 假设要提前说明;不确定就问——不要猜。存在多种解释时,把它们列出来让用户选择——不要默默选定一种。
- 有更简单的方案就提出;必要时据理力争。
- 被卡住就停下;明确说清哪里不明白。

### 简单优先

- 写解决问题的最少代码;不做未要求的功能、抽象或配置项。
- 不为不可能发生的场景添加防御性错误处理。
- diff 不必要地变大时要裁剪。

### 外科手术式修改

- 只碰与任务直接相关的行;不要顺手"清理"附近的代码、注释或格式。
- 不要因为工作代码的风格与你不同就重构或统一风格。
- 无关的死代码:提一句,不要主动删除。
- 清理**你自己**引入的孤儿 import、变量和函数。

### 可验证的结果

| 任务 | 计划 | 验证 |
|------|------|------|
| Bug 修复 | 先写一个能复现的失败测试 → 修复 → 跑套件 | 修复前新测试失败;修复后 `make test` 通过 |
| 新公共 API | 从 `__init__.py` 的 `__all__` 导出 → 实现 + docstring + 测试 + README 提及 | `make all` 绿 |
| 行为变更 | 先增/改测试 → 再改实现 | 定向 `pytest`,然后 `make all` |
| 重构 | 重构前 `make test` → 重构 → 重构后 `make test` | 除非另有要求,行为零变化 |

**交付标准:`make all` 全绿**(format + lint + typecheck + test——与 pre-commit 钩子运行的内容完全一致)。多步工作先拟一个简短计划:

```
1. 读 backends/workspace.py 的 resolve_path → 验证:理解 root_dir 与 workspace_dir 的区别
2. 实现 xxx → 验证:pytest tests/test_backends_utils.py -k xxx
3. 跑完整门禁 → 验证:make all
```

## 2. 这是什么

`octop-harness` 是一个已发布的 Python 库(`pip install octop-harness`)。它是 [LangChain Deep Agents](https://docs.langchain.com/oss/python/deepagents/) 的适度封装,让用户用极少的代码创建生产级 agent。

**它是库,不是应用。** 任何看起来像应用层的功能(cron、MBTI 引导、向量记忆持久化、HTTP 服务器、用户登录、UI)都不属于这里——它们属于 Octop 等宿主。`octop-harness` 提供 agent 运行时;`octop-gateway`(IM 桥)和 Octop(自托管平台)在其上组装应用。

## 3. 技术栈

| 层 | 技术 |
|-------|------------|
| 语言 | Python 3.12+;每个源文件都有 `from __future__ import annotations` |
| Agent 运行时 | `deepagents>=0.7,<0.8` + `langchain` / `langchain-core` / `langgraph` |
| 配置对象 | `dataclasses`(`HarnessAgentConfig` / `ProviderConfig` / `ModelConfig`),带 `to_dict` / `from_dict` |
| 可选 extras | `cli`(click + rich + prompt-toolkit)、`bedrock`、`remote-backends`、`docker`、`opensandbox`、`observability`(langfuse)、`acp`、`desktop`(mss + pynput + pillow)、`web-search-all`、`object-storage`、`all` |
| 生态 | `octop-memory`、`octop-browser`、`langchain-mcp-adapters` + `mcp` |
| 打包 | hatchling;本地开发用 `uv`(`uv sync --group dev`) |
| 质量门禁 | ruff(lint + format,行宽 120)、`mypy --strict`、pytest + pytest-asyncio |

## 4. 包结构

```
src/octop_harness/
├── __init__.py             # 公共导出 + 类型 stub + HarnessAgent / Workspace 的懒加载
├── _version.py             # 经 importlib.metadata 解析 pyproject.toml 的 [project].version
├── agent.py                # HarnessAgent(构造 + invoke/stream + init())
├── manager.py              # HarnessAgentManager + 多 agent 编排 + team 子系统
├── registry.py             # 内存 agent 注册表(AgentEntry + 存储 CRUD)
├── request.py              # ChatRequest(messages/thread_id/user/source/...)
├── config/                 # HarnessAgentConfig + ProviderConfig + ModelConfig + env 解析
├── init.py                 # init_workspace + InitResult(工作区种子)
├── backends/               # Backend 字符串 / dict → BackendProtocol 实例
│   ├── workspace.py        # BackendWorkspace:L1 agent 存储门面
│   └── utils.py            # 路径规则 + backend I/O 辅助 + materialize_storage_path
├── llm/                    # ChatModelFactory(ProviderConfig → BaseChatModel)+ 模型路由
├── middleware/             # SessionLogger / PII / memory / 媒体卸载等
├── memory/                 # MemoryRuntime(octop-memory 适配器)
├── media/                  # 供应商无关的媒体生成(BaseMediaProvider + 内置实现)
├── plugins/                # 插件系统(manifest / loader / registry / tools / context)
├── providers/              # provider_template.json(预设)+ load_provider_templates()
├── protocols/              # 聊天协议注册表(发现 / 解析实现)
├── security/               # 策略模型(FilesystemPolicy / HitlPolicy / SSRF)+ tool_guard
├── skills/                 # Skill 目录与元数据辅助
├── slash/                  # 运行时斜杠命令(stop / skills / model)
├── subagents/              # 工作区子 agent 加载与目录
├── teams/                  # 可选的收件箱驱动的 agent 间协作
├── acp/                    # ACP(Agent Client Protocol)外部 agent 集成
├── observability/          # 可选可观测(langfuse)+ 运行时日志
├── context_usage.py        # 上下文窗口用量估算 / 持久化
├── compaction.py           # 强制会话压缩(SummarizationMiddleware 卸载 + 摘要)
├── messages.py / usage.py  # 消息解析 / token 用量归一化
├── runtime_env.py          # 进程 env + 全局键 + 工作区 .env 合并
├── mcp.py                  # MCP server 配置合并 + 工具加载
├── cli/                    # 可选 CLI(main / commands / agents / config / providers / repl / ui)
└── builtin/
    ├── _sync.py            # 把 builtin/skills/* 同步到 workspace/_builtin_skills/
    ├── templates.py        # 打包 builtin/ 资源的纯读取层
    ├── md_files/           # 用户工作区模板(en/ zh/)
    ├── agents/             # 内置工作区子 agent 定义(en/ zh/,YAML frontmatter + system_prompt)
    ├── skills/             # 内置 skills(en/ zh/,启动时同步)
    └── tools/              # 内置工具(current_time / web_fetch / send_file / screenshot / web_search/*)

tests/                      # pytest,与 src 模块一一对应
examples/                   # 端到端可运行示例(带编号)
learning/                   # 源码学习课程(16 本中文 notebook;不进质量门禁与发布产物)
multi_agent_demo/           # 多 agent 示例配置
chat_demo/                  # Vue 3 + FastAPI(SSE) 聊天界面演示（演示层代码；不进包、门禁与发布产物）
```

**改动定位速查:**

| 要改… | 看… |
|------------|----------|
| 公共 API(构造函数 / 字段) | `agent.py` / `config/` / `request.py` |
| 多 agent 注册 / 路由 / 取消 | `manager.py` / `registry.py` |
| 新内置工具 | `builtin/tools/*.py` + `builtin/tools/__init__.py` |
| 新内置 skill | `builtin/skills/{en,zh}/<name>/SKILL.md` |
| 新 backend | `backends/__init__.py`(注册)+ `backends/<name>.py`(实现) |
| 路径 / backend 存储 | `backends/utils.py` / `backends/workspace.py` |
| 配置序列化 | `config/` |
| 启动行为 | `agent.py` 中 `HarnessAgent.__init__` 的组装 |
| Provider 预设列表 | `providers/provider_template.json` |
| CLI 子命令 | `cli/commands/*_cmd.py` + `cli/main.py` |

## 5. 模块边界

### 分层(自底向上;禁止反向 import)

| 层 | 模块 | 职责 |
|-------|--------|------|
| L0 | `backends/utils.py` | 低层 I/O 辅助(`backend_write_force` 等);`materialize_storage_path` 逃生口 |
| L1 | `backends/workspace.py`(`BackendWorkspace`) | harness 内**agent 可见 / agent 使用的工作区内容**的**唯一** I/O 门面 |
| L2 | `middleware/*`、`builtin/tools/*`、`init.py`、`builtin/_sync.py` | 业务 / 种子逻辑;L1 内容只经 `BackendWorkspace`;运行时持久化可作为显式例外直接落本地 FS / DB |
| L3 | `agent.py` | 组装;`config` 只解析路径片段,自身不做 I/O |

### 该走哪条路径

| 调用方 | 入口 | 说明 |
|--------|-------|-------|
| 内部 L1 内容(init、bootstrap、skills、媒体、绑定的 send_file、目录清单,…) | `agent.workspace` / `BackendWorkspace` | **必须** |
| LLM 工具(`read_file` / `write_file`) | `agent.backend` | deepagents 协议;由 backend 的 `virtual_mode` / `root_dir` 解释 |
| 本地运行时持久化(memory DB、`sessions/` JSONL、`checkpoints.sqlite`) | `Path` / `open()` / DB 驱动,默认在 `workspace_dir` 下 | 显式例外:真实 OS fd、锁、append 或轮转——不经 `BackendWorkspace` |
| 运行时诊断日志(`octop_harness.*`) | `Path` / logging handler,默认 `~/.octop-harness/logs` | 应用层 `HarnessAgentManager(log_dir=…)` / `setup_logging`;多 agent 共享,带 `[agent=…]` 前缀 |
| CLI 全局配置(`~/.octop-harness/`) | 本地 FS | 不属于 agent 工作区 |

这里说的"agent 内容"指模板、bootstrap、skills、媒体、send-file 落盘目标,以及其他被 agent / LLM 使用的工作区内容。它们的读写只经 `BackendWorkspace`——绝不用 `Path` / `open()` 直接操作。不要用 `Path(workspace_dir).read_text()` / `open()` 绕过 `BackendWorkspace` 访问 L1 内容。但这条禁令**不**延伸到上表中本地运行时持久化的条目。

## 6. 常用命令

```bash
# 完整门禁(提交前必须通过;也是 pre-commit 钩子运行的内容)
make all                    # = format + lint + typecheck + test

# 单独的目标
make format                 # ruff check --fix + ruff format(会改写文件)
make lint                   # ruff check + ruff format --check
make typecheck              # mypy --strict
make test                   # pytest(带覆盖率)

# 直接用 venv(make 不方便时)
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy --strict src
.venv/bin/python -m pytest -q

# 环境
make install-hooks          # 每个 clone 一次:启用 .githooks pre-commit
make install                # uv sync --group dev(别名:make install-dev)
uv sync --all-extras        # 全部可选 extras(等同 pip install 'octop-harness[cli,all]')

# 打包
make build                  # wheel + sdist 输出到 dist/
make version                # 打印当前版本

# 跑一个示例
.venv/bin/python examples/06_init_and_md_files.py
```

**单测调试:** `pytest tests/test_init.py::TestInitWorkspace::test_idempotent_second_call_skips -xvs`

**Git 钩子(本地提交必须):** clone 后先执行一次 **`make install-hooks`**。它会设置 `core.hooksPath=.githooks`,此后每次 `git commit` 都会先跑 **`make all`**(`format` 会改写文件,然后 lint / typecheck / test)。被 format 改写的暂存文件会自动重新 add,提交内容是格式化后的。仅在紧急情况绕过:`SKIP_PRECOMMIT=1 git commit …` 或 `git commit --no-verify`——**不要**为了提交一套红灯的代码而跳过钩子。

## 7. 关键约定

### 库 vs 应用

- **可以加:** deepagents 的薄封装、公共 API、可选 backend / 工具 / skill、序列化。
- **不得加:** HTTP 服务器、本地数据库、cron 守护进程、向量记忆持久化、UI、登录 / 用户管理。这些是应用层关注点。

### 默认值哲学

- **零依赖优先:** 核心 `pip install octop-harness` 不携带可选依赖;重型依赖(`mss`、`langchain-tavily`,…)走 `[extras]`。
- **体验可 fail-soft,检查不 fail-soft:** fail-soft 只适用于启动 / 调用时的用户体验,不适用于 mypy / lint。缺失的 backend extras 要报清晰的错误并告诉用户该装什么;测试和类型检查保持严格。
- **用户编辑是神圣的:** `init()` 默认不覆盖已有文件;`overwrite=True` 强制刷新。`builtin/skills` 的擦除替换只在版本戳不同时发生。

### 命名

- 工具函数 / 模块 / 文件 / 包:`snake_case`;不用连字符。
- Skill 目录:`kebab-case`(`skill-creator/`、`web-search/`)——Anthropic 生态的事实标准;用 `importlib.resources.files(...).iterdir()` 枚举(`Traversable` 不要求合法 Python 包名)。
- 类:`PascalCase`(`HarnessAgent`、`InitResult`)。

### Agent 工作区与 `BackendWorkspace`

#### `root_dir` vs `workspace_dir`(不同维度;不要混为一谈)

| | `root_dir` | `workspace_dir` |
|---|---|---|
| **是什么** | 构建本地 backend(`filesystem` / `local_shell`)时的挂载参数 | Agent 的**推荐工作目录**(宿主机绝对路径,或 agent 视角的 rootfs 路径) |
| **谁在用** | 仅 `resolve_backend` / deepagents backend 构建 | `HarnessAgentConfig`、harness 组装、`BackendWorkspace` |
| **对 agent / LLM 可见?** | **否**——不是工具 API 概念 | 工作区语义;相对路径以它为基准 |
| **典型角色** | 虚拟 `/` 在磁盘上的落点 | SOUL/skills/种子文件及部分运行时持久化的默认基底 |

**不要**把它们当成"两棵对等的树"或"agent 在 root 和 workspace 之间做选择"。Agent 只看到路径约定;`root_dir` 是 backend 组装细节。

工厂行为,简述:

- 若 spec **未**固定 `root_dir`,则用 `workspace_dir` 填充 → 虚拟 `/` 与工作区对齐(常见,推荐)。
- 默认 spec 固定 `root_dir="/"` + `virtual_mode=True` → backend 看到整台机器;`workspace_dir` 仍是推荐工作区(且在宿主根目录时工厂会包一层 composite,让 deepagents 的卸载落到工作区)。
- `workspace_dir` 可以是宿主机绝对路径,也可以是 agent 视角的 rootfs 路径(如 `/.octop/workspaces/<id>`)。后者由 harness 先映射到 `{root_dir}/…` 再做本地持久化,在 Windows 上也合法(无盘符)。对齐配置下,工作区内容与从 `/` 出发的虚拟 FS 路径一一对应(如 `/SOUL.md` → `{workspace_dir}/SOUL.md`)。

#### `virtual_mode=True`(默认)且 `root_dir` 不是宿主 `/`

deepagents 文件系统工具此时把 `/foo` 映射到 `{root_dir}/foo`(实现细节;agent 入口仍是 rootfs 路径,harness 在工具入口**不**拼接 `root_dir`)。

**`BubbledLocalShellBackend`(仅 Linux + bwrap + 非宿主 `root_dir` + `virtual_mode`)**

- 只有这些条件同时满足工厂才选它;否则选 `HarnessLocalShellBackend`(dotenv 刷新、保守的可信虚拟路径映射)。
- 目录监禁只作用于 `execute`:把 `root_dir` 绑定为监禁内的 `/`。
- 工作区内的路径限制由 deepagents / 监禁负责;命令串保持 agent 视角,不做改写。
- 监禁 cwd 对齐虚拟 `workspace_dir`(工作区不在 `root_dir` 下时回退到 `/`)。

**无监禁(macOS / 无 bwrap / 宿主根)**

- `execute` 以宿主工作区为 cwd 运行。
- 非宿主根且 `virtual_mode=True` 时,命令 token 与 env 中的可信虚拟绝对路径映射到 `{root_dir}/…`:已存在的宿主路径优先;否则只允许工作区内部路径、或拥有现存虚拟树祖先的路径。URL、真实的 `/usr` / `/tmp`、宿主绝对路径保持不变。
- execute 输出中的 `root_dir` 前缀还原为 agent 视角的 `/…`。
- 读取产物时在 `BackendWorkspace` 读侧做**多层回退**:
  - **绝对路径:** 先试 `{root_dir}` 映射(`backend._resolve_path`);缺失再试原始宿主路径。
  - **相对路径:** 先试 `{root_dir}/{rel}`,再试 `{workspace_dir}/{rel}`。
- 绑定的 `materialize_local` / `exists` / `aexists` / `read_text` / `aread_text` / `download_bytes` / `send_file` 都走这套回退。

```text
model: write_file("/gen/run.py") + execute("python /gen/run.py")
        │                              │
        ▼                              ▼
  deepagents → {root}/gen/run.py    bwrap: 监禁内的 /gen/...
                                    无监禁: 可信虚拟路径映射到 {root}/gen/...
model / harness 随后读取产物:
  BackendWorkspace.materialize_local("/gen/out.pptx")
    → 先 {root}/gen/out.pptx,再原始 /gen/out.pptx
      (相对路径: root → workspace)
```

#### `BackendWorkspace.resolve_path` 速查

| 输入 | 结果 |
|-------|--------|
| 不以 `/` 开头 | `{workspace_dir}/{fragment}` |
| 以 `/` 开头 | `virtual_mode` 下经 `backend._resolve_path` 映射到 `root_dir`;否则原样返回 |
| `~/…` | `expanduser()` 之后的宿主路径 |

逃逸 `workspace_dir` 的相对路径(如 `../x`)→ `PermissionError`。
`skill_paths()` / `memory_paths()` 经 `_backend_storage_key`(`virtual_mode` 下是 agent 视角的虚拟 `/…` 键,**不**与 `root_dir` 拼接)交给 deepagents Skills/Memory 中间件做 `backend.ls` 与系统提示注入;宿主 I/O / 物化仍用 `resolve_path`。

```python
ws = agent.workspace
ws.write_text("AGENTS.md", text, force=True)
agent.init_workspace()
```

### 严格懒导入

- 可选 SDK(`mss`、`langchain_tavily`、`qcloud_cos`,…)只在调用时导入,绝不在模块顶层导入。
- 用 ruff per-file-ignore 豁免 `PLC0415`;不要用内联 `# noqa`(它与 per-file-ignore 冲突并触发 `RUF100`)。
- 遵循 `pyproject.toml` 中 `[tool.ruff.lint.per-file-ignores]` 已有的注释模式。

## 8. 常见坑

- **`HarnessAgentConfig` 是 frozen dataclass:** 加字段必须同时更新 `to_dict` / `from_dict`(包括 `_unserializable_fields` 和 `_xxx_to_jsonable` 辅助)。`providers` 现在是 `list[ProviderConfig]`,序列化为 JSON 数组而非对象;`ProviderConfig` 有 `id` 字段,构造时必须传。
- **`ProviderConfig` 必须传 `id`:** `id` 是第一个位置参数(必填,无默认值)。手写 `ProviderConfig(base_url=..., api_key=...)` 必须加 `id=`;JSON 反序列化走 `from_dict`(旧 dict 格式向后兼容)。
- **mypy strict 不允许隐式 `Any` 返回:** 返回 `Any` 的第三方 SDK 调用要显式 `cast` 或 `assert isinstance(...)`,否则报 `no-any-return`。
- **`mss` 等可选包的 mypy:** 在 `[[tool.mypy.overrides]]` 下加 `ignore_missing_imports = true`。**不要**用 `# type: ignore[import-not-found]`(装上 extra 后会变成 `unused-ignore`)。
- **deepagents skills / memory 路径:** `skill_paths()` / `memory_paths()` 经 `_backend_storage_key` 交给 deepagents(`virtual_mode` → 虚拟 `/…` 键;不要拼接宿主 `root_dir`)。`resolve_path` 只用于宿主 I/O / 物化(见 [§7](#agent-工作区与-backendworkspace))。
- **L1 agent 存储:** agent 可见 / agent 使用的工作区内容走 `agent.workspace`(`BackendWorkspace`);memory DB、日志、JSONL 转写、checkpoint SQLite 是本地运行时持久化,直接用本地 FS / DB 驱动。不要把 `root_dir` 当成第二个工作区。
- **shell / virtual_mode:** 非宿主根 + `virtual_mode` + Linux + bwrap → 工厂选 `BubbledLocalShellBackend` 监禁 `execute`;否则 `HarnessLocalShellBackend` 保守映射可信的命令 / env 虚拟路径并以工作区为 cwd。读取仍有 `BackendWorkspace` 的 root→原始 / root→workspace 回退(见 [§7](#agent-工作区与-backendworkspace))。
- **不要在模块顶层 import `mss`:** 在函数内导入,否则未装 `[desktop]` 的 `pip install octop-harness` 用户执行 `import octop_harness.builtin.tools` 会挂。
- **`init.py` 不得 `from octop_harness import __version__`:** 会循环导入。用 `from octop_harness._version import __version__`(版本唯一来源是 `pyproject.toml` 的 `[project].version`)。
- **`HarnessAgentManager` 是推荐入口:** `manager.create_agent(config)` 立即构建并缓存 `HarnessAgent`;`manager.stream(agent_id, request)` 复用缓存实例。直接 `HarnessAgent(config)` 仍支持纯 backend 用途(`agent.backend`、`agent.init_workspace()`),但**所有 LLM 对话都走 manager**。
- **`HarnessAgentManager` 是单进程内存注册表:** 不要跨进程共享同一实例;跨进程协调留给 MQ 扩展点(接口已预留)。
- **CLI 用 `CliAgentManager`,不直接用库的 `HarnessAgentManager`:** `cli/agents/manager.py` 的 `CliAgentManager` 负责文件持久化,经 `.runtime` 触达底层 manager。
- **Provider 预设放 JSON,不放 Python:** `providers/provider_template.json` 是唯一事实来源;`cli/providers/registry.py` 的 `_build_registry()` 读该 JSON。不要在 Python 里硬编码新 provider。

## 9. 测试约定

- **测试文件与 `src/` 模块一一对应:** `src/octop_harness/init.py` ↔ `tests/test_init.py`;子包有对应目录(`tests/cli/`、`tests/config/`、`tests/protocols/`、`tests/slash/`、`tests/observability/`)。
- **Mock 第三方 SDK;不走网络:** 所有 web-search / S3 / COS 测试用 mock 客户端;只有 `examples/` 可以用真实网络。
- **断言行为而非实现:** `test_idempotent_second_call_skips` 检查 `templates_skipped` 列表,而不是 `_sync.py` 的内部分支。
- **正则匹配用原始字符串:** `pytest.raises(RuntimeError, match=r"env var.*missing")`,否则 `RUF043`。
- **跨平台:** CI 跑 Linux,但代码必须兼容 Windows / macOS。POSIX 专属行为(bwrap、`chmod`、`/proc`)用 `pytest.mark.skipif` 守卫;优先 `tmp_path` / `pathlib.Path` 相等断言,避免硬编码 `/` 前缀字符串。参见 `tests/test_bwrap_shell*.py`、`tests/test_docker_sandbox.py`。
- **PR 前:** 全套件绿、mypy 0 问题、ruff 干净——CI 跑同样的内容。

## 10. 禁止事项

边界规则见 [§5](#5-模块边界)。此外:

- 不要用 `Path` / `open()` 绕过 `BackendWorkspace` 访问 L1 agent 内容(本地运行时持久化的例外见 [§5 该走哪条路径](#该走哪条路径))。
- 不要在模块顶层导入可选 SDK;不要用内联 `# noqa: PLC0415`。
- 不要加应用层功能:HTTP 服务器、cron 守护进程、UI、登录 / 用户管理、向量记忆持久化。
- 不要提交真实凭据:`.env` / `.gitignore` 已覆盖;`pyproject.toml` 里也不得有 API key。
- 不要在 README / docstring / 测试里硬编码真实凭据:用 `"sk-xxx"` 占位符。若用户粘贴了密钥,不要把完整字符串回显进提交信息 / 日志,并提醒用户吊销。
- 不要为演示禁用 PII Middleware,除非演示的主题就是关闭 PII。
- 不要在 `cli/*_cmd.py` 里复制 manager / config 的领域逻辑。
- 用户没有明确要求时不要 `git commit` / `git push`。

## 11. 去哪找

| 问题 | 位置 |
|----------|----------|
| 如何构造 / 调用 agent? | `agent.py`、`manager.py`、`tests/test_agent.py` |
| 多 agent 注册与路由 | `manager.py`、`registry.py` |
| 工作区初始化(种子文件 / skills) | `init.py`、`builtin/templates.py`、`builtin/_sync.py` |
| backend 解析与路径规则 | `backends/__init__.py`、`backends/utils.py`、`backends/workspace.py` |
| shell / 沙箱行为 | 本地 shell backend 实现、`tests/test_bwrap_shell*.py`、`tests/test_docker_sandbox.py` |
| Provider 预设 / 模型工厂 | `providers/provider_template.json`、`llm/` |
| 中间件(PII / memory / 媒体卸载) | `middleware/` |
| 内置工具 | `builtin/tools/` |
| 插件系统 | `plugins/` |
| teams / subagents / ACP | `teams/`、`subagents/`、`acp/` |
| 配置字段与 env 解析 | `config/` |
| CLI 行为 | `cli/main.py`、`cli/commands/*_cmd.py` |
| 发布流程与钩子 | [§12](#12-变更流程);`CONTRIBUTING.md` |

外部参考:

- [LangChain Deep Agents 文档](https://docs.langchain.com/oss/python/deepagents/)
- [LangGraph 中间件指南](https://docs.langchain.com/oss/python/langchain/middleware)

## 12. 变更流程

1. **先读:** 要改动文件的 docstring、相邻实现、相关规格。
2. **钩子:** 若本 clone 还没跑过 `make install-hooks`,先跑(见 [§6](#6-常用命令))。提交前钩子必须保持绿。
3. **小步前进:** 能拆多个提交就拆;一个提交,一个动机。
4. **docstring 与测试同步:** 签名 / 行为变了,docstring + 测试一起更新。
5. **新公共 API 必须:** 进 `__init__.py` 的 `__all__`、有 docstring、有测试覆盖、README 至少提及一次。
6. **质量门禁:** `make all` 必须全绿——pre-commit 跑的就是它;钩子失败就不要提交。某条规则确实需要豁免时,加 per-file-ignore 并注释**原因**。
7. **CHANGELOG:** 用户可见的公共行为变化在 `CHANGELOG.md` 的 `## [Unreleased]` 下加一行。
8. **收尾:** 清理本次改动引入的孤儿符号;未被要求就不要 commit 或 push。

### 分支与发布

```
feature/* ──PR──► develop ──► release/x.y.z ──PR──► main ──tag v*──► publish
hotfix/* ──PR──► main(+ tag)并 ──PR──► develop
```

| 分支 | 角色 |
|--------|------|
| `main` | 生产事实来源;**默认分支**;只接受 release / hotfix 合并;**只有 `main` 上的 `v*` 标签是生产版本** |
| `develop` | 日常集成;**feature PR 的基线** |
| `release/x.y.z` | 临时冻结(版本号 / CHANGELOG / README 同步);**发布后删除** |
| `hotfix/*` | 从 `main` 出发的紧急修复;合回 `main` 并回 `develop` |

**规则**

- 绝不把 `develop` 直接推上 `main`——只能经 `release/*` → `main`(或 hotfix → `main`)发布。**不要**把 `develop` 批量合并到 `main`;那会分叉历史并破坏发布后的同步。
- 绝不直接 push 到 `main` 或 `develop`——一律开 PR(GitHub 分支保护)。
- `release/*` → `main` 用 **merge commit**(不要 squash)合并,保证 `main` 与 `develop` 可持续对账。
- 发布顺序:从最新 `develop` 切 `release/*` → PR 进 `main` → **合并后才在 main 顶端打 `v*` 标签** → 删除 `release/*` → Actions 把 `main` 同步回 `develop`(`sync-main-to-develop.yml`;冲突 / 分支保护时开 `chore/sync-develop-after-*`)。
- 每次发布后保持 **`main` 是 `develop` 的祖先**。不要用旧式 `head=main` → `develop` 的同步 PR。
- 在进入 `main` 之前**不要**从 release / feature 分支推生产标签。
- Hotfix:从 `main` 拉分支,PR 进 `main`(要发布就打标签),然后 PR 进 `develop`。
- 日常 feature:从 `develop` 拉分支,PR **进 `develop`**(不是 `main`)。
- 人工细节见 `CONTRIBUTING.md`。Agent 发布流程:`.cursor/skills/publish` / `.codebuddy/skills/publish`。


## 13. 沟通规范

- 与用户交流默认用**中文**;代码引用写成 `` `path:line` ``。
- 先给结论,再给细节;写完整句子,不写电报式碎片。
- 说"完成"之前,附上验证命令及其结果(或说明为什么没跑)。
- 范围外的问题简单带过;不要单方面扩大范围。
- **质量门禁全绿之前不要说"完成":** `make all` 没有全绿,就不能宣布收工。

---

_本文件是活文档——结构、约定或流程变化时保持同步。_
