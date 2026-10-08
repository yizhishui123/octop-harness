# %% [markdown]
# # 02 · HarnessAgent 组装流水线
#
# **学习目标**
#
# - 逐行读懂 `HarnessAgent.__init__` 的装配顺序——它就是整个库的骨架目录;
# - 弄清 `_build_tools` / `_build_middleware` / `_build_graph` 三大子装配;
# - 建立 **路径双轴模型**(`workspace_dir` vs `root_dir`)的直觉——本库大半的"玄学"都源于这两根轴;
# - 理解 checkpointer 的三级选择逻辑。
#
# 源码:`src/octop_harness/agent.py`(约 2000 行,本系列最核心的一本)。
#
# 实验方式延续 00 介绍的**离线假模型**:`HarnessAgent(model_factory=fake)` 只换"模型的嘴",
# 其余装配全部真实。

# %%
# —— 标准前置(每本 notebook 自带,便于独立阅读)——
import sys
from pathlib import Path

HERE = Path.cwd()
REPO = HERE.parent if HERE.name == "learning" else HERE
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

WORKSPACES = REPO / "learning" / ".workspaces"

def show(path: str, start: int, end: int) -> None:
    """带行号打印仓库内源码片段"""
    lines = (REPO / path).read_text(encoding="utf-8").splitlines()
    for i in range(start - 1, min(end, len(lines))):
        print(f"{i + 1:5d} │ {lines[i]}")

from langchain_core.messages import AIMessage
from octop_harness import HarnessAgent, HarnessAgentConfig

from learning.support.fake_model import FakeChatModelFactory, FAKE_MODEL_REF, fake_providers

print("ok, 仓库根:", REPO)

# %% [markdown]
# ## 1. 装配流水线总览
#
# `__init__`(`agent.py:145-202`)按依赖顺序装配,顺序本身就是架构图:
#
# | # | 步骤 | 位置 | 干什么 |
# |---|------|------|--------|
# | 1 | `_init_paths` | :1050 | 快照 `workspace_dir` |
# | 2 | `_host_workspace_path` | :1099 | 把 rootfs 路径(`/.octop/...`)映射到 `{root_dir}/...` |
# | 3 | `_init_logging` | :1172 | 装库级默认日志(`~/.octop-harness/logs`) |
# | 4 | `_init_mcp` | :1179 | 校验/加载 MCP server 配置(失败只警告,不炸) |
# | 5 | `_build_backend` | :1290 | `resolve_backend(...)` 造出 BackendProtocol |
# | 6 | 构建 `BackendWorkspace` | :167 | L1 唯一 I/O 门面(第 06 本主角) |
# | 7 | `.env` 接线 | :1323 | 让 local_shell 的 execute 能读到工作区 `.env` |
# | 8 | `_init_model_factory` | :1197 | 注入工厂 → cfg.providers → 环境探测,全空报错 |
# | 9 | `MemoryRuntime` | `memory/runtime.py:36` | 记忆子系统(含 aux LLM) |
# | 10 | `_init_graph` | :1240 | = `_build_tools` + `_build_middleware` + `_build_graph` |
# | 11 | `_init_protocols` | :1286 | 预热默认协议(langgraph) |
# | 12 | `factory.bind_runtime` + 插件绑定 | :190 | 编译后的协议钩子 |

# %%
show("src/octop_harness/agent.py", 145, 202)

# %% [markdown]
# 读这段代码时注意三处"不易察觉"的设计:
#
# 1. **fail-soft 的边界**:`_init_mcp` 里 MCP 加载失败只是 warning——启动体验优先;
#    但 `_init_model_factory` 找不到任何 provider 直接 raise——没有模型就不是 agent。
# 2. **backend 先于 workspace**:L1 门面 `BackendWorkspace` 要包着建好的 backend 才能构造。
# 3. **图编译放在最后**:工具、中间件、子代理、系统提示全都就位后才调 `create_deep_agent`。

# %%
# 活体实验:真的组装一个 agent,然后检查装配产物
import shutil

WS = WORKSPACES / "nb02"
if WS.exists():
    shutil.rmtree(WS)
WS.mkdir(parents=True)

cfg = HarnessAgentConfig(
    workspace_dir=WS,
    providers=fake_providers(),
    default_model=FAKE_MODEL_REF,
    memory_enabled=False,      # 关闭记忆,聚焦组装本身(记忆在第 13 本)
    web_search_tools=False,    # 精简工具表(工具表本身马上讲)
)
factory = FakeChatModelFactory(["你好,组装完成。"])
agent = HarnessAgent(cfg, model_factory=factory)

print("backend 类型      :", type(agent.backend).__name__)
print("backend.root_dir  :", getattr(agent.backend, "root_dir", "<无>"))
print("backend.virtual_mode:", getattr(agent.backend, "virtual_mode", "<无>"))
print("workspace 类型    :", type(agent.workspace).__name__)
print("model_factory 类型:", type(agent.model_factory).__name__)
print("graph 类型        :", type(agent.graph).__name__)

# %% [markdown]
# 注意 `virtual_mode=True` 且 `root_dir` 是宿主 `/`——这是**默认 backend spec**:
# ```python
# DEFAULT_BACKEND_SPEC = {"type": "local_shell", "root_dir": "/", "virtual_mode": True}
# ```
# 也就是说:**默认配置下 agent 拥有整台机器的 shell 权限**(构造时会打 warning)。
# 限制是显式 opt-in 的——这是有意的"信任宿主"设计,也是安全评审的第一着眼点。

# %%
# 图里有哪些节点?(deepagents 的 CompiledStateGraph)
print("graph 节点:", list(agent.graph.nodes))

# %% [markdown]
# ## 2. 路径双轴模型:`workspace_dir` vs `root_dir`
#
# | | `root_dir` | `workspace_dir` |
# |---|---|---|
# | **是什么** | 构建本地 backend 时的挂载参数(虚拟 `/` 落在哪) | agent 的**推荐工作目录** |
# | **谁在用** | 只有 `resolve_backend` / backend 构建 | `HarnessAgentConfig`、组装线、`BackendWorkspace` |
# | **agent 可见?** | **否**(不是工具 API 概念) | 是;相对路径以它为基准 |
#
# **不要**把它们当"两棵对等的树"。agent 只看到路径约定;`root_dir` 是实现细节。
#
# 工厂规则(`backends/__init__.py`):
#
# - spec **没固定** `root_dir` → 用 `workspace_dir` 填充 → 虚拟 `/` 与工作区对齐(**推荐**);
# - 默认 spec 固定 `root_dir="/"` → 看到整台机器;
# - 云后端(s3/postgres/cos/oss/obs)**无视** `root_dir`,有自己的编址。

# %%
from octop_harness.backends import resolve_backend

# 形态一:spec 不固定 root_dir → 与 workspace 对齐
b_aligned = resolve_backend({"type": "filesystem"}, workspace_dir=WS, system_files_path=".octop")
print("对齐形态  : root_dir =", getattr(b_aligned, "root_dir", "?"),
      "| virtual_mode =", getattr(b_aligned, "virtual_mode", "?"))

# 形态二:默认 spec(等价于 None)→ 宿主根
b_default = resolve_backend(None, workspace_dir=WS, system_files_path=".octop")
print("默认形态  : root_dir =", getattr(b_default, "root_dir", "?"),
      "| virtual_mode =", getattr(b_default, "virtual_mode", "?"),
      "| 类型 =", type(b_default).__name__)

# %% [markdown]
# 默认形态得到的不是裸 backend,而是被 **composite 包装**过的(名字里带 Composite):
# 工厂在宿主根场景会包一层 `MountedCompositeBackend`,把 deepagents 的会话历史/媒体卸载
# 引导到 `{workspace}/.octop` 下,避免把 `/` 或 `~/` 弄乱(`_maybe_wrap_workspace_artifacts`,
# `backends/__init__.py:258`)。第 08 本会拆开讲。
#
# ### `BackendWorkspace.resolve_path` 速查(第 06 本逐条实验)
#
# | 输入 | 结果 |
# |------|------|
# | 不以 `/` 开头(`AGENTS.md`) | `{workspace_dir}/AGENTS.md` |
# | 以 `/` 开心(`/SOUL.md`) | virtual_mode 下经 `backend._resolve_path` 映射到 `root_dir` 下 |
# | `~/…` | `expanduser()` 后的宿主路径 |

# %%
# 现场感受三种输入的映射(用刚才组装好的 agent)
for fragment in ("AGENTS.md", "/SOUL.md", "~/x.md"):
    print(f"resolve_path({fragment!r:12s}) →", agent.workspace.resolve_path(fragment))

# %% [markdown]
# ## 3. `_build_tools`:工具从哪来
#
# `agent.py:1341-1370`。分四档:
#
# 1. **永远有**:current_time / web_fetch / browser_use / desktop_screenshot / send_file_to_user / env_file 工具;
# 2. **按配置**:`load_web_search_tools(cfg.web_search_tools)`、ask_user、媒体生成、记忆工具;
# 3. **用户自带**:`cfg.tools`;
# 4. **最后追加**:ACP runner、MCP 工具。

# %%
show("src/octop_harness/agent.py", 1341, 1370)

# %%
# web_search 的四种策略是纯注册表逻辑,可以离线把玩
from octop_harness.builtin.tools.web_search._registry import load_web_search_tools

for policy in (False, "auto", "all", ["searchfree"]):
    tools = load_web_search_tools(policy)
    print(f"web_search_tools={policy!r:24s} → {[t.name for t in tools]}")

# 注意"auto"是体验优先(缺 Key 的静默跳过);但**显式点名**是严格校验:
try:
    load_web_search_tools(["tavily"])   # 本机没有 TAVILY_API_KEY
except RuntimeError as e:
    print("\n显式点名缺 Key →", e)

# %% [markdown]
# `False` 关闭;`"auto"` 挑环境变量齐全的(searchfree 不需要 Key,永远在);`"all"` 全注册;
# 显式列表按名单。上面最后那个异常是刻意保留的教学点:**"auto" 走体验优先(缺 Key 静默跳过),
# 显式点名走严格校验(缺 Key 直接报错并告诉你缺什么)**——"fail-soft 给体验,不给检查"的活例子。
#
# ## 4. `_build_middleware`:21 层策略流水线(顺序即策略)
#
# `agent.py:1422-1564`。完整顺序与每层的排序理由在**第 04 本**逐层拆,这里先看装配代码的骨架:
# 条件中间件是"插空"加入的,`BootstrapMiddleware` 甚至最后插到 index 0——
# 顺序不是书写顺序,而是**精心计算的插入顺序**。

# %%
show("src/octop_harness/agent.py", 1422, 1437)   # docstring:顺序契约
print("……")
show("src/octop_harness/agent.py", 1559, 1564)   # Bootstrap 插入 index 0

# %% [markdown]
# ## 5. `_build_graph`:交给 deepagents 编译
#
# `agent.py:1663-1767`。要点:
#
# - 系统提示 = `cfg.system_prompt` + **硬编码的工作目录指令**(:1687-1698)+ 媒体策略 + 技能提示;
# - `subagents` 经 `_resolve_subagents`(:1619)合并工作区 `agents/**/*.md` 与 `cfg.subagents`,
#   并**剥离 MCP 工具与 ask_user_question**——子图不跑父级中间件/HITL,带着这些工具会出事故;
# - `interrupt_on` 来自安全策略(HITL 审批门);
# - 最妙的一手:**临时 monkeypatch `deepagents.graph.create_summarization_middleware`**(:1740-1764),
#   抓住 deepagents 内部创建的 SummarizationMiddleware 实例(供 `/compact` 事后调参),
#   并注入"recall 感知"的 token 计数器。try/finally 恢复,补丁只活在编译那一瞬间。

# %%
show("src/octop_harness/agent.py", 1740, 1764)

# %% [markdown]
# ## 6. checkpointer 三级选择
#
# `_resolve_checkpointer`(`agent.py:1788`):
#
# 1. `cfg.checkpointer = False` → 显式关闭;
# 2. 用户传入实例 → 直接用;
# 3. **记忆开启时:直接复用 `Memory` 实例当 checkpointer**——SQLite 一库两用,检查点与记忆共享同一份真相(`agent.py:1812`);
# 4. 兜底:默认 `AsyncSqliteSaver` 写 `{workspace}/checkpoints.sqlite`(:1822)。
#
# 兜底路径有两个工程细节值得记:aiosqlite 工作线程被标记 daemon(不阻塞进程退出);
# 同步构造 `AsyncSqliteSaver` 需要临时事件循环(`_build_async_sqlite_saver`, :1931)。

# %%
# 跑一轮对话,看看工作区里长出了什么(checkpointer 落地证据)
res = await agent.call("组装检查:请回复一句话。")
messages = res["messages"]
print("对话消息:", [(type(m).__name__, (m.content or "")[:24]) for m in messages])
print()
print("工作区内容:")
for p in sorted(WS.rglob("*")):
    if p.is_file() and ".ipynb_checkpoints" not in str(p):
        print("  ", p.relative_to(WS))

await agent.aclose()

# %% [markdown]
# `checkpoints.sqlite` 出现了——这就是第 4 级兜底 checkpointer 的落盘证据(记忆关闭时)。
# 第 07 本会拿 sqlite3 直接打开它看表结构。
#
# ## 7. 组装完成之后:热更新面
#
# 图不是一次性焊死的,`HarnessAgent` 提供了热更新 API:
#
# | API | 行号 | 语义 |
# |-----|------|------|
# | `set_skills_disabled` / `set_tools_disabled` | :334 | 不重编译,运行时开关 |
# | `append_mcp_tools` / `replace_mcp_tools` | :277 | 增量换 MCP 工具表 |
# | `reload_subagents` | :357 | 重扫 `agents/` 并重编译图 |
# | `set_langfuse_callbacks` | :1262 | 热挂可观测 |
#
# (Manager 层还有"热重建整个 agent"的 `rebuild_all_agents`,第 15 本讲。)
#
# ## 8. 思考题
#
# 1. 为什么用"seed model + 逐轮 ModelRouter"双层设计,而不是每次调用都新建模型?(提示:图编译时需要一个具体模型;缓存/会话头/session 复用)
# 2. monkeypatch `create_summarization_middleware` 是"黑魔法",它规避了什么问题?如果 deepagents 未来暴露官方钩子,这段代码该怎么迁移?
# 3. 子代理为什么要剥离 MCP 与 ask_user 工具?如果你想让子代理也能问用户,应该改哪一层?
# 4. `Memory` 实例兼任 checkpointer,"一库两用"省了什么、又引入了什么风险?(第 07 本回看)
#
# ## 9. 延伸阅读
#
# - `tests/test_agent.py` —— 组装契约的测试镜像
# - 第 03 本:[03_message_lifecycle.ipynb](03_message_lifecycle.ipynb) —— 让这条组装线真的跑起来
# - deepagents 文档:https://docs.langchain.com/oss/python/deepagents/

# %% [markdown]
# <details><summary>附:清理本 notebook 的工作区(可选运行)</summary>

# %%
# 想回收实验空间时运行:
# shutil.rmtree(WS, ignore_errors=True)
print("保留工作区供检查:", WS)
