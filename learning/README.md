# learning/ — octop-harness 源码学习课程

以 Jupyter notebook 形式系统性学习 `octop-harness` 的架构设计、理念、流程、SQL 与沙箱。
面向已熟悉 Python + deepagents + Harness 常见理念的读者,聚焦**本仓库特有的设计决策**。

## 快速开始

```bash
# 1. 安装依赖(dev + learning 两个依赖组)
uv sync --group dev --group learning

# 2. 一次性注册具名内核(指向本仓库 .venv;VS Code / Jupyter 都靠它选中环境)
uv run python -m ipykernel install --user --name octop-harness --display-name "octop-harness (.venv)"

# 3. 启动 JupyterLab(仓库根目录执行)
uv run jupyter lab learning/
```

打开任意 `NN_*.ipynb` 顺序学习即可。**所有实验离线可跑**:不需要 API Key、不访问网络;
涉及真实 LLM 的内容都标注了 `[可选·需 Key]`。

### 用 VS Code 学习

用 VS Code 打开**仓库根目录**(不要只开 `learning/` 子目录,否则看不到 `.venv`),
装好 Python + Jupyter 两个官方扩展后打开任意 `NN_*.ipynb`,右上角内核选择器里选:

- **Jupyter Kernels → octop-harness (.venv)**(上面第 2 步注册的,任何文件夹视角都可见);或
- **Python Environments → .venv**。

想撤销内核注册:`jupyter kernelspec uninstall octop-harness`。

## 课程地图(五模块 · 16 本)

| 模块 | notebook | 主题 | 状态 |
|------|----------|------|------|
| 一 · 全景与主线 | `00_overview` | 架构总览、分层模型、学习地图 | ✅ |
| | `01_config_system` | 配置三件套、序列化契约、env 探测、三大理念 | ✅ |
| | `02_agent_assembly` | `__init__` 装配流水线、路径双轴、checkpointer 三级选择 | ✅ |
| | `03_message_lifecycle` | 一条消息的完整旅程、thread/取消/斜杠/协议层 | ✅ |
| 二 · 中间件与模型路由 | `04_middleware_pipeline` | 21 层中间件顺序哲学、自定义中间件、PII/媒体卸载实验 | ✅ |
| | `05_model_routing_and_context` | 逐轮路由优先级链、TurnAwareProfile、用量估算、强制压缩 | ✅ |
| 三 · 存储与 SQL | `06_backend_workspace` | L0-L3 边界、resolve_path、materialize 多层回退 | ✅ |
| | `07_sql_deep_dive` | checkpoints.sqlite / memory.sqlite / Postgres 后端 SQL | ✅ |
| | `08_backend_factory_and_cloud` | resolve_backend 工厂、composite 包装、云后端嵌套键 | ✅ |
| 四 · 沙箱 | `09_local_shell_no_jail` | 无监禁的启发式可信路径翻译(macOS 可真跑) | ✅ |
| | `10_bwrap_jail` | Linux bwrap 监禁解剖(argv/ro-binds/cwd 对齐) | ✅ |
| | `11_docker_and_remote` | DockerSandbox「同路径两处」、资源限额、OpenSandbox | ✅ |
| 五 · 生态与扩展 | `12_seeding_skills_subagents` | 种子流程、版本戳、en/zh 回退、子代理加载 | ✅ |
| | `13_memory_and_teams` | MemoryRuntime、recall 快照、Teams inbox | ✅ |
| | `14_security_stack` | SecurityPolicy、FilesystemGuard 双路径、ToolGuard、SSRF | ✅ |
| | `15_extensions` | Manager 热重建、CLI 两层、插件、MCP、可观测 | ✅ |

## 目录结构

```
learning/
├── NN_*.ipynb        # 学习 notebook(主产物,含已执行的输出)
├── nb_src/NN_*.py    # notebook 的 percent 格式源码(纯文本,便于 diff 与再生成)
├── support/
│   ├── fake_model.py         # 离线脚本化假模型 + 假工厂(见下)
│   └── build_notebooks.py    # 从 nb_src/ 重建 ipynb
├── .workspaces/      # 实验工作区(gitignored,可随时删)
└── .gitignore
```

## 离线可跑的秘密

流程类实验需要"会说话的模型",但不依赖 API Key:`support/fake_model.py` 的
`FakeChatModelFactory` 继承真实 `ChatModelFactory`,只覆写 `get_chat_model()` 返回
按剧本回复的 `ScriptedChatModel`,经 `HarnessAgent(model_factory=...)` 注入点进入组装线。
于是**中间件、工具、后端、checkpointer 全是真的,只有"模型的嘴"是假的**。

## 修改/再生成 notebook

notebook 主产物是 `.ipynb`,但建议改 `nb_src/*.py`(percent 格式)再重建:

```bash
uv run python learning/support/build_notebooks.py        # 全部重建
uv run python learning/support/build_notebooks.py 04     # 只重建 04
# 重建会清掉输出,记得重新执行验证:
uv run jupyter nbconvert --to notebook --execute --inplace learning/04_middleware_pipeline.ipynb
```

`nb_src/*.py` 的 markdown cell 按 jupytext 惯例逐行以 `# ` 注释(构建时自动剥掉),
因此源码文件也能直接在 VS Code 的 Interactive Window 里当 notebook 读。

## 约定

- 实验工作区一律落在 `learning/.workspaces/`(已 gitignore),不碰用户目录;
- `learning/` 不进 ruff/mypy/pytest 的质量门禁(`make all` 只扫 `src` 与 `tests`);
- notebook 里的 `show("src/...", 起, 止)` 会带行号打印源码片段——行号以当前源码为准,
  若与仓库演进不一致,以函数名/内容为准。
