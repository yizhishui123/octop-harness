# %% [markdown]
# # 15 · 扩展生态:Manager 热重建、CLI、插件、MCP、协议、可观测
#
# **学习目标(本系列收官)**
# - Manager 的**热重建**与 agent 的**延迟关闭**(in-flight 保护);
# - CLI 的**两层管理器**(文件画像 vs 运行时注册表);
# - 插件系统(plugin.yaml / pip 安装 requires / PluginContext 授权 API);
# - MCP 工具加载的硬功夫(pydantic null 剥离、活跃优先);
# - 协议注册表与 langfuse 可观测的挂法;
# - runtime_env 的四种"生成环境"(host/docker/ACP/MCP stdio)。
#
# 这是"地图补全"本——每节都短,给你留好 file:line 入口。

# %%
# —— 标准前置(每本 notebook 自带,便于独立阅读)——
import sys
from pathlib import Path

HERE = Path.cwd()
REPO = HERE.parent if HERE.name == "learning" else HERE
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

def show(path: str, start: int, end: int) -> None:
    """带行号打印仓库内源码片段"""
    lines = (REPO / path).read_text(encoding="utf-8").splitlines()
    for i in range(start - 1, min(end, len(lines))):
        print(f"{i + 1:5d} │ {lines[i]}")

print("ok, 仓库根:", REPO)

# %% [markdown]
# ## 1. Manager 热重建 + 延迟关闭
#
# `set_security_policy` / `rebuild_all_agents`(`manager.py:103/107`)会**移除再重建**所有 agent;
# 重建包在 `hold_shared_memory` 里(记忆连接池存活,13 本讲过)。
# 单个 agent 的 `close()` 在 `_in_flight > 0` 时**挂起**,最后一个在飞的调用收尾时才真正释放
# (`agent.py:940-976`)——热更新不打断正在进行的对话:

# %%
show("src/octop_harness/agent.py", 940, 956)

# %% [markdown]
# 还有个异步细节:`aremove_agent` 刻意**不用** `to_thread`——aiosqlite 连接绑在事件循环上,
# 挪线程就废了(`manager.py:282-289` 注释)。
#
# ## 2. CLI:两层管理器
#
# `cli/agents/manager.py:18` 的 `CliAgentManager` 只管**持久化**(画像 JSON 存
# `~/.octop-harness/config.json`),运行时全部委托 `.runtime`(库的 `HarnessAgentManager`)。
# "文件画像"与"进程内注册表"分离,是宿主接入的标准姿势——Octop 也是同样思路。

# %%
show("src/octop_harness/cli/agents/manager.py", 18, 36)

# %% [markdown]
# CLI 命令面(`cli/main.py`):`agent`(增删查默认)、`chat`(REPL / `-p` 一次性)、`config`、
# `skill`、`init`、`update`。REPL 的斜杠命令经 `cli/repl/slash_router.py` 桥接到 03 本的运行时分发器。
#
# ## 3. 插件系统:setup(ctx) 一切从这开始
#
# 插件 = 一个目录 + `plugin.yaml`(id/version/kind/entry/requires)。加载器会
# **pip 安装 requires**(subprocess)、把入口模块导入为 `harness_plugin_<id>`,再调 `setup(ctx)`:

# %%
show("src/octop_harness/plugins/context.py", 1, 40)

# %% [markdown]
# `ctx.tool / ctx.middleware / ctx.skills_dir` 就是插件作者的整个 API 面;
# 工具的**每次调用配置**从 `RunnableConfig.configurable["plugin_tool_configs"]` 读——
# 插件工具默认启用,agent 可按名 opt-out。
#
# ## 4. MCP:三层硬功夫
#
# `mcp.py` 干三件事,每件都有坑要填:
#
# 1. **合并**:manager 级 + agent 级 server 配置,agent 胜(`merge_mcp_server_configs`);
# 2. **加载**:每 server 一个 `MultiServerMCPClient`(带名字前缀)——一台 server 挂了不拖累别人;
#    在运行中的事件循环里同步加载时,借一个单线程 ThreadPoolExecutor 溜出去(`mcp.py:247-254`);
# 3. **args 模型加固**:MCP `inputSchema` → pydantic 模型时,把 `anyOf:[T,null]` 与
#    `default:null` **从 LLM 可见面里剥掉**——模型太爱填 null,而很多 MCP server(Zod 系)收到 null 直接报错:

# %%
from octop_harness.mcp import _strip_nullables_from_json_schema

schema = {
    "type": "object",
    "properties": {
        "title": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        "page_size": {"type": "integer"},
    },
}
_strip_nullables_from_json_schema(schema)
print("剥掉 nullable 后:", schema["properties"]["title"])
print("不受影响:", schema["properties"]["page_size"])

# %% [markdown]
# 另一个实用细节:`prioritize_active_mcp_tools`(`mcp.py:270`)把**活跃 server** 的工具排前——
# 有些供应商会悄悄截断超长工具列表,把最可能用到的放前面是朴素有效的防御。
#
# ## 5. 协议注册表:三种出口形态
#
# 03 本见过三协议;这里是注册机制本身——自定义协议只要继承 `ChatProtocol` 并注册:

# %%
from octop_harness import resolve_protocol

proto = resolve_protocol("langgraph", graph=object())
print("langgraph 协议实例:", type(proto).__name__)
try:
    resolve_protocol("nope", graph=object())
except ValueError as e:
    print("未注册协议 →", e)

# %% [markdown]
# ## 6. 可观测:langfuse 热挂 + 进程级日志
#
# `LangfuseTracer`(`observability/langfuse.py:30`)懒加载回调,经
# `agent.set_langfuse_callbacks` **热挂**到已编译的图(`graph.with_config`);凭据按指纹轮换;
# 每请求的 session/user/agent 元数据由 manager 的 `_enrich_request` 注入,`after_call` 钩子 flush。
# 日志是进程级的:按天滚动文件,默认 `~/.octop-harness/logs`,多 agent 记录带 `[agent=…]` 前缀:

# %%
from octop_harness import default_log_dir

print("库默认日志目录:", default_log_dir())

# %% [markdown]
# ## 7. runtime_env:四种"生成环境"故意不同
#
# `runtime_env.py` 模块 docstring 值得整段读——同一个"环境变量从哪来"的问题,
# 四种子进程面有**四种故意不同**的答案:
#
# | 面 | env 策略 |
# |----|----------|
# | host execute(09 本) | 完整 `os.environ` + extra + 工作区 `.env` |
# | docker(11 本) | 最小 `PATH`/`HOME` 基底,**绝不**透传宿主全量 |
# | ACP 子进程 | 完整 `os.environ`(外部 agent 运行时是受信的) |
# | MCP stdio | SDK 默认子集 + spec env |
#
# 且 `PROTECTED_ENV_KEYS` + `OCTOP_*` 前缀保护——工作区 `.env` **不能**冒充平台身份。
#
# ## 8. 媒体生成 SPI(速览)
#
# `media/`:`BaseMediaProvider` 模板方法基类(共享 httpx、提交/轮询/超时助手),
# 内置 volcengine / dashscope / minimax 三家;`MediaManager` 路由 image/video 任务,
# 产物经 `WorkspaceMediaArtifactStore` 落 BackendWorkspace(又是 L1 门面)。
# 有 API Key 才挂 `generate_image` / `generate_video` 工具(04 本的工具清单见过)。
#
# ## 9. 结业:把整张地图串起来
#
# ```text
# 配置(01) ──► 组装(02) ──► 对话(03)
#                │                │
#     中间件链(04)+ 路由/上下文(05)
#                │
#     存储(06)+ SQL(07)+ 工厂/云(08)
#                │
#     沙箱三态:翻译(09)/ bwrap(10)/ docker·远程(11)
#                │
#     种子·技能·子代理(12)+ 记忆·Teams(13)+ 安全(14)
#                │
#     扩展面:Manager 热重建 / CLI / 插件 / MCP / 协议 / 可观测(15,本本)
# ```
#
# ## 10. 思考题(结业)
#
# 1. 给这个库加一个"每 agent 独立 token 预算"功能,你会动哪些模块?(提示:中间件 + context_usage + manager 元数据)
# 2. 如果宿主要多进程部署,`HarnessAgentManager` 的单进程假设(AGENTS.md §8)哪里先崩?
# 3. 从 00 到 15,找出三处"刻意不对称"(同类问题故意用不同方案),并解释各自的理由。
# 4. 现在让你给这个库写一版 v2 API,你会保留什么、砍掉什么、为什么?
#
# ## 11. 延伸阅读
#
# - `tests/plugins/`、`tests/test_mcp*.py`、`tests/protocols/`、`tests/observability/`
# - `examples/` 全目录(带编号,按需取用;多数需 Key)
# - `CONTRIBUTING.md` —— 贡献与发布流程(AGENTS.md §12 的展开)
# - **课程完**。回到 [README](README.md) 复盘学习路径。
