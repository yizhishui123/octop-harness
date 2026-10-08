# %% [markdown]
# # 00 · 全景导览:octop-harness 是什么、长什么样
#
# **学习目标**
# - 用 10 分钟建立整个仓库的心智地图:它是什么、不是什么、代码怎么分层;
# - 认识本系列 16 本 notebook 的学习路线;
# - 学会本系列的"源码导读法"(`file:line` + `show()` 工具),后面每本都靠它精读源码。
#
# **前置**:你已了解 Python 3.12+、deepagents 框架与 Harness 的常见理念(中间件、后端、检查点等)。本系列聚焦**本仓库特有的设计决策**,不科普基础概念。
#
# **本本 notebook 全部离线可跑**:不需要 API Key、不访问网络。涉及真实 LLM 的章节都会标注 `[可选·需 Key]` 并在无 Key 时自动跳过。

# %%
# —— 标准前置(每本 notebook 自带,便于独立阅读)——
import sys
from pathlib import Path

HERE = Path.cwd()
REPO = HERE.parent if HERE.name == "learning" else HERE
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

WORKSPACES = REPO / "learning" / ".workspaces"  # 所有实验工作区都落在这里(已 gitignore)
WORKSPACES.mkdir(parents=True, exist_ok=True)

def show(path: str, start: int, end: int) -> None:
    """带行号打印仓库内源码片段,如 show("src/octop_harness/agent.py", 145, 202)"""
    lines = (REPO / path).read_text(encoding="utf-8").splitlines()
    for i in range(start - 1, min(end, len(lines))):
        print(f"{i + 1:5d} │ {lines[i]}")

import octop_harness

print("仓库根:", REPO)
print("octop-harness 版本:", octop_harness.__version__)

# %% [markdown]
# ## 1. 一句话定位
#
# `octop-harness` 是一个**已发布的 Python 库**(`pip install octop-harness`),对
# [LangChain Deep Agents](https://docs.langchain.com/oss/python/deepagents/) 做了一层"适度封装"——
# 目标是让用户用极少的代码得到生产级 agent(自带会话检查点、技能、记忆、PII 脱敏、沙箱、多 agent 协作……)。
#
# **它是库,不是应用。** 这是整个仓库最重要的一条边界(见 `AGENTS.md` §2/§7):
#
# | 归属 | 例子 |
# |---|---|
# | **属于本库**(agent 运行时) | 中间件、后端/沙箱、配置序列化、内置工具/技能、多 agent 注册表 |
# | **不属于本库**(应用层,归宿主) | HTTP 服务器、cron 守护、向量库、UI、登录/用户管理、IM 网关 |
#
# 宿主生态:`octop-gateway`(IM 桥)与 Octop(自托管平台)在它之上组装应用。记住这条边界,后面看任何代码都会想通"为什么这里只做一半"。
#
# > 另一个易混点:仓库根的 `AGENTS.md` 讲**如何改这个仓库**;而 `src/octop_harness/builtin/md_files/AGENTS.md` 是**给终端用户工作区的模板**,讲如何使用本库创建的 agent。两份文档不要搞混。

# %%
# 眼见为实:src/octop_harness 的顶层结构
SRC = REPO / "src" / "octop_harness"
entries = sorted(SRC.iterdir(), key=lambda p: (p.is_file(), p.name))
print(f"src/octop_harness/  共 {len(entries)} 个顶层条目\n")
for p in entries:
    kind = "目录" if p.is_dir() else "文件"
    print(f"  [{kind}] {p.name}")

# %%
# 公共 API 有多少?顶层 __init__ 只做惰性重导出(lazy export)
print(octop_harness.__all__)

# %% [markdown]
# 可以看到公共面非常克制:`HarnessAgent` / `HarnessAgentManager` / 配置三件套 / `ChatRequest` /
# `init_workspace` / 协议与安全少量符号。其余全部是内部实现——这就是"库"的自觉。
#
# ## 2. 架构总览:一条消息的生命线
#
# ```text
# ChatRequest(str | dict | ChatRequest)                request.py
#   └─ HarnessAgentManager.stream/call(agent_id, req)  manager.py   ← 多 agent 注册/路由/取消
#        └─ HarnessAgent.call / stream                 agent.py     ← 组装产物在此被调用
#             ├─ 斜杠命令拦截(/model /stop /compact)   slash/
#             ├─ _prepare_call:消息归一化 + runnable config
#             └─ ChatProtocol(langgraph|openai|mcp)    protocols/
#                  └─ deepagents CompiledStateGraph    _build_graph() 编译产物
#                       ├─ 中间件链(21 层,顺序即策略)  middleware/
#                       │    ModelRouter → … → PII → 媒体卸载 → 记忆 → … → ContextUsage
#                       ├─ 工具(内置 + 用户 + MCP + team)  builtin/tools/
#                       ├─ 后端(文件系统/本地 shell/沙箱/云)  backends/
#                       └─ checkpointer(SQLite/Postgres)  → 会话持久化
# ```
#
# 三个"心脏":
# - **`agent.py`(约 2000 行)** —— 组装车间,所有部件在这里拧在一起;
# - **`manager.py` + `registry.py`** —— 多 agent 的注册表与编排入口;
# - **`backends/`** —— 一切 I/O 的地基(路径规则、沙箱、云存储都在这)。

# %% [markdown]
# ## 3. 分层模型:谁可以 import 谁
#
# | 层 | 模块 | 职责 |
# |----|------|------|
# | L0 | `backends/utils.py` | 低层 I/O 辅助(`backend_write_force` 等) |
# | L1 | `backends/workspace.py`(`BackendWorkspace`) | **agent 可见内容**的唯一 I/O 门面 |
# | L2 | `middleware/*`、`builtin/tools/*`、`init.py`、`builtin/_sync.py` | 业务/种子逻辑 |
# | L3 | `agent.py` | 纯组装 |
#
# 禁止反向 import;L2 读写 agent 工作区内容**必须**走 L1 的 `BackendWorkspace`
# (例外:memory 数据库、JSONL 会话日志、checkpoints.sqlite 属于"本地运行时持久化",可以直接用文件系统)。
# 这套边界在 `AGENTS.md` §5 有精确表格,第 06 本 notebook 会用实验逐条验证。

# %% [markdown]
# ## 4. 动手:种一个工作区看看
#
# agent 的工作区长什么样?`init_workspace()` 会把模板 md、内置技能、内置子 agent 定义种进去。
# 这一步**完全离线**,是认识"agent 世界"的最快方式。

# %%
import shutil
from octop_harness import init_workspace

WS = WORKSPACES / "nb00"
if WS.exists():
    shutil.rmtree(WS)

result = init_workspace(WS, language="zh")
print("InitResult 字段:", [f for f in dir(result) if not f.startswith("_")])
print("写入的模板:", [Path(t).name for t in result.templates_created])
print("技能是否同步:", result.skills_synced)
print("种子 agent:", [Path(t).name for t in result.agents_created])

# %%
def print_tree(base: Path, prefix: str = "", max_depth: int = 2, depth: int = 0) -> None:
    if depth > max_depth:
        return
    entries = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name))
    for i, p in enumerate(entries):
        connector = "└── " if i == len(entries) - 1 else "├── "
        print(prefix + connector + p.name + ("/" if p.is_dir() else ""))
        if p.is_dir():
            print_tree(p, prefix + ("    " if i == len(entries) - 1 else "│   "), max_depth, depth + 1)

print(f"{WS}/")
print_tree(WS, max_depth=1)

# %%
# 幂等性:再种一次会怎样?(理念:用户编辑是神圣的,默认不覆盖)
result2 = init_workspace(WS, language="zh")
print("第二次 templates_created:", result2.templates_created)
print("第二次 templates_skipped:", result2.templates_skipped)

# %% [markdown]
# 第二次调用什么都不写——`init()` 默认不覆盖已有文件(`overwrite=True` 才强制刷新)。
# 这就是本库三大默认值哲学之一的"**用户编辑神圣**"(另外两条:**零依赖优先**、**体验 fail-soft 但检查严格**,
# 第 01 本详解)。
#
# ## 5. 本系列学习地图
#
# | 模块 | notebook | 主题 |
# |------|----------|------|
# | 一 · 全景与主线 | 00-03 | 总览 / 配置体系 / Agent 组装 / 一条消息的完整旅程 |
# | 二 · 中间件与模型路由 | 04-05 | 21 层中间件的顺序哲学 / 逐轮换模型与上下文压缩 |
# | 三 · 存储与 SQL | 06-08 | BackendWorkspace 门面 / SQL 三落点 / 后端工厂与云存储 |
# | 四 · 沙箱 | 09-11 | 无监禁的启发式翻译 / bwrap 监禁 / Docker 与远程沙箱 |
# | 五 · 生态与扩展 | 12-15 | 种子与技能子代理 / 记忆与 Teams / 安全 / Manager·CLI·插件·MCP |
#
# 建议顺序刷,但每本都可独立阅读。**配套读法**:每本都会给出 `file:line`,请在编辑器里对照打开源码;
# notebook 里的 `show()` 也随时能打印片段。
#
# ### 离线运行的秘密(后面各本通用)
#
# 流程类实验需要一个"会说话的模型",但我们不想依赖 API Key。本系列的解法:
# `learning/support/fake_model.py` 提供了一个**脚本化假模型工厂**——
# 继承真实的 `ChatModelFactory`,只覆写 `get_chat_model()` 返回按剧本回复的假模型,
# 经 `HarnessAgent(model_factory=...)` 注入点(`agent.py:149`)进入组装线。
# 于是:**中间件、工具、后端、checkpointer 全是真的,只有"模型的嘴"是假的**。
# 这本身就是理解本库"组装与模型解耦"设计的最好实验。

# %% [markdown]
# ## 6. 思考题
#
# 1. 库与应用的边界:如果让你加"用户登录",应该改哪里?(答案:不是这里——是 Octop 宿主)
# 2. `src/octop_harness/builtin/` 下的东西(ml_files/skills/agents/tools)在**安装到用户机器后**扮演什么角色?
# 3. 为什么 `__init__.py` 用惰性导出而不是直接 import?(提示:`pip install octop-harness` 不带任何 extra 时,import 包也不该炸)
#
# ## 7. 延伸阅读
#
# - `AGENTS.md`(仓库根)—— 本仓库的"工作手册",本系列的很多表格源于它
# - `README.md` / `README_CN.md` —— 用户视角的功能介绍
# - `examples/01_quickstart.py` —— 推荐的第一个真实示例(需 Key)
# - 下一本:[01_config_system.ipynb](01_config_system.ipynb) —— 配置体系与三大理念
