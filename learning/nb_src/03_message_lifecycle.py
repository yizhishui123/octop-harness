# %% [markdown]
# # 03 · 一次对话的完整旅程
#
# **学习目标**
#
# - 跟着一条消息从 `ChatRequest` 走到流式 token,把 00 的静态地图变成动态体验;
# - 验证 thread(线程)= checkpointer 的持久化单位:同 thread 历史累积,跨 thread 互不干扰;
# - 观察一次**真实的工具调用轮次**(脚本化 tool_call + 真实工具执行);
# - 体验斜杠命令拦截、以及"取消"为什么是一场赛跑。
#
# 全程离线:假模型说话,其余全真。

# %%
# —— 标准前置(每本 notebook 自带,便于独立阅读)——
import asyncio
import shutil
import sys
import time
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

from octop_harness import AgentEventType, HarnessAgent, HarnessAgentConfig, HarnessAgentManager, init_workspace
from octop_harness.request import ChatRequest

from learning.support.fake_model import FakeChatModelFactory, FAKE_MODEL_REF, fake_providers

# 实验工作区通常没有用户级 skills/ 目录,deepagents 的 Skills 中间件会对每个根发一条
# "Cannot load skills" 提示(空目录告警,无害)。压掉它让输出聚焦:
import logging
logging.getLogger("deepagents.middleware.skills").setLevel(logging.ERROR)

print("ok, 仓库根:", REPO)

# %% [markdown]
# ## 1. 全链路地图(带着走)
#
# ```text
# ChatRequest("现在几点?", thread_id="t1")            request.py:27  dataclass + coerce
#   │  coerce: str/dict/ChatRequest 三态归一          request.py:85
#   ▼
# HarnessAgentManager.stream(agent_id, req)           manager.py:377
#   │  _prepare_request:盖 agent_id/langfuse 章       manager.py:347
#   ▼
# HarnessAgent.stream(req)                            agent.py:475
#   │  斜杠命令拦截(/model /stop /compact …)         slash/runtime.py
#   │  _prepare_call:消息归一 + runnable config       agent.py:1869
#   │  session_header_scope(thread_id)                llm/session_header.py
#   ▼
# ChatProtocol(langgraph).stream                      protocols/langgraph.py
#   ▼
# graph.astream(deepagents CompiledStateGraph)
#   │  中间件链逐层包裹模型调用(04 本)
#   │  工具执行(current_time 等真实代码)             builtin/tools/
#   │  checkpointer 逐轮落盘(07 本)
#   ▼
# 事件流:STATE_SNAPSHOT → TOKEN → TOOL_RESULT → … → USAGE
# ```

# %%
# 准备一个"真实感"的 agent:这次先 init_workspace 种子工作区
WS = WORKSPACES / "nb03"
if WS.exists():
    shutil.rmtree(WS)
init_workspace(WS, language="zh")

cfg = HarnessAgentConfig(
    workspace_dir=WS,
    providers=fake_providers(),
    default_model=FAKE_MODEL_REF,
    memory_enabled=False,
    web_search_tools=False,
)
factory = FakeChatModelFactory([
    "第一轮:你好,我是离线假模型。",
    "第二轮:我记得你上一句说了什么。",
    "第三轮:再见。",
])
agent = HarnessAgent(cfg, model_factory=factory)
print("agent 就绪,工作区已种子")

# %% [markdown]
# ## 2. `call()`:一次完整调用
#
# 返回值是协议层包装的 dict,`messages` 是**本轮新增**的消息(含工具轮次)。
# 注意每条消息 `additional_kwargs` 上的两个戳:
#
# - `checkpoint_ts`(CheckpointTsMiddleware 盖的时间戳,`aget_history` 的快路径靠它);
# - `context_usage`(最后一层中间件 ContextUsageMiddleware 的用量快照,05 本细讲)。

# %%
res = await agent.call(ChatRequest(messages="打个招呼", thread_id="t1"))
for m in res["messages"]:
    print(f"  {type(m).__name__:14s} content={str(m.content)[:30]!r}")
last_ai = res["messages"][-1]
print("\nAIMessage 的 additional_kwargs 键:", list(last_ai.additional_kwargs))
print("checkpoint_ts =", last_ai.additional_kwargs.get("checkpoint_ts"))

# %% [markdown]
# ## 3. thread:checkpointer 的持久化单位
#
# 同一个 `thread_id` 再来一轮,历史应当增长;换一个 thread 则从零开始。
# 这就是 LangGraph checkpointer 的语义——agent 自己只是无状态图。

# %%
res2 = await agent.call(ChatRequest(messages="我上一句说了什么?", thread_id="t1"))
hist_t1 = await agent.aget_history("t1")
hist_t2 = await agent.aget_history("t-other")
print(f"thread t1 历史 {len(hist_t1)} 条 | 最新回复: {hist_t1[-1].content!r}")
print(f"thread t-other 历史 {len(hist_t2)} 条(全新线程)")

ckpt = WS / "checkpoints.sqlite"
print(f"\ncheckpoints.sqlite 存在: {ckpt.exists()}  大小: {ckpt.stat().st_size if ckpt.exists() else 0} bytes")

# %% [markdown]
# ## 4. `stream()`:事件流 + 一次真实的工具调用
#
# 这次给假模型编排一个 `tool_calls`:第一轮它"决定"调 `current_time` 工具
# (工具是**真实执行**的——读系统时钟,离线可跑),第二轮基于工具结果作答。
# 这正是 deepagents 的 ReAct 循环,只是"决策"来自剧本。

# %%
from octop_harness.builtin.tools.current_time import CurrentTimeTool   # 只是证明工具是真实代码

WS2 = WORKSPACES / "nb03b"
if WS2.exists():
    shutil.rmtree(WS2)
init_workspace(WS2, language="zh")
cfg2 = HarnessAgentConfig(
    workspace_dir=WS2,
    providers=fake_providers(),
    default_model=FAKE_MODEL_REF,
    memory_enabled=False,
    web_search_tools=False,
)
factory2 = FakeChatModelFactory([
    AIMessage(content="", tool_calls=[{"name": "current_time", "args": {}, "id": "call_1"}]),
    "根据工具结果:刚才那一轮我调用了 current_time。",
])
agent2 = HarnessAgent(cfg2, model_factory=factory2)

token_text, tool_events = [], []
async for ev in agent2.stream(ChatRequest(messages="现在几点?", thread_id="s1")):
    et = ev["type"]
    if et == AgentEventType.TOKEN:
        token_text.append(ev["content"])
    elif et == AgentEventType.TOOL_RESULT:
        tool_events.append(ev)
    elif et in (AgentEventType.STATE_SNAPSHOT, AgentEventType.STATE_UPDATE):
        pass  # 结构性事件,05 本再看
    else:
        print("其他事件:", et)

print("TOKEN 拼出的文本:", "".join(token_text))
print("TOOL_RESULT 事件数:", len(tool_events))

# %%
# 工具结果里真的是当前时间吗?
raw = tool_events[0].get("content") if tool_events else None
print("TOOL_RESULT 原始内容(截断):", str(raw)[:200])

# %% [markdown]
# ## 5. 斜杠命令:不进图,直接短路
#
# `/model`、`/stop`、`/skills`、`/compact` 这类命令在 `HarnessAgent.call/stream` 入口就被
# `slash/runtime.py` 拦截,**根本不会到模型**。走 manager 路径演示(顺便认识多 agent 注册表):
#
# > 诚实说明:`HarnessAgent` 有公开的 `model_factory=` 注入参数,但 `HarnessAgentManager`
# > 没有对外暴露工厂注入——它构造时自建 `self._shared_factory`(manager.py:71)。
# > notebook 里我们替换这个内部属性来离线化,这本身就是对 API 面的一次观察。

# %%
mgr = HarnessAgentManager(providers=fake_providers())
mgr._shared_factory = FakeChatModelFactory(["manager 路径的回复。"])   # 内部缝隙(见上)
entry = mgr.create_agent(cfg2, agent_id="demo", init_workspace=False)
print("注册表中的 agent:", [e.agent_id for e in mgr.list_agents()])

async for ev in mgr.stream("demo", ChatRequest(messages="/model fake/fake-model", thread_id="s2")):
    if ev.get("type") == AgentEventType.TOKEN:
        print("".join([ev["content"]]), end="")
print()
print("get_thread_model →", mgr.get_thread_model("demo", "s2"))

# %%
# /skills list:同样被拦截(不经过模型)
async for ev in mgr.stream("demo", ChatRequest(messages="/skills list", thread_id="s2")):
    if ev.get("type") == AgentEventType.TOKEN:
        print(ev["content"], end="")
print()

# %% [markdown]
# `/model` 之后,该 thread 的模型覆盖写进了 `configurable["model"]`,
# 由 `ModelRouterMiddleware` 在每一轮读取(05 本做路由实验)。
#
# ## 6. 取消:一场赛跑,不是一个标志位
#
# 假模型即时返回,看不出取消的意义。这里在 notebook 里现场造一个"慢模型":
# `_generate` 里 `time.sleep(3)`。注意 `stream()` 若用"块间查标志"的方式实现,
# 取消必须等到下一个 token——而 LLM 的 await 可能阻塞很久。
# `_iter_until_cancelled`(`agent.py:396`)把 `__anext__` 与取消事件放进 `asyncio.wait`
# **赛跑**,谁先完成听谁的,所以取消能抢占阻塞中的模型调用。

# %%
show("src/octop_harness/agent.py", 396, 413)

# %%
from learning.support.fake_model import ScriptedChatModel

class SlowChatModel(ScriptedChatModel):
    """睡 3 秒再回话的假模型,用来暴露取消语义。"""
    slow_seconds: int = 3

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        time.sleep(self.slow_seconds)   # 同步 _generate 由执行器线程跑,不会卡住事件循环
        return super()._generate(messages, stop, run_manager, **kwargs)

slow_factory = FakeChatModelFactory(["迟到的回复——如果你看到我,说明取消失败了。"])
slow_factory._scripted = SlowChatModel(queue=slow_factory._scripted.queue)

WS3 = WORKSPACES / "nb03c"
if WS3.exists():
    shutil.rmtree(WS3)
cfg3 = HarnessAgentConfig(
    workspace_dir=WS3, providers=fake_providers(), default_model=FAKE_MODEL_REF,
    memory_enabled=False, web_search_tools=False,
)
agent3 = HarnessAgent(cfg3, model_factory=slow_factory)

async def consume() -> tuple[int, int, float]:
    tokens, events, t0 = 0, 0, time.perf_counter()
    async for ev in agent3.stream(ChatRequest(messages="慢点说", thread_id="c1")):
        events += 1
        if ev.get("type") == AgentEventType.TOKEN:
            tokens += 1
    return tokens, events, time.perf_counter() - t0

task = asyncio.create_task(consume())
await asyncio.sleep(0.5)                      # 让流进入模型 await
agent3.cancel("c1")                           # agent 级取消(manager.cancel 会两级一起设)
tokens, events, elapsed = await task
print(f"耗时 {elapsed:.2f}s 即返回(模型本身要睡 3s)——取消抢占了阻塞中的模型调用")
print(f"收到 TOKEN {tokens} 条(0 = 没等到模型开口)、结构性事件 {events - tokens} 条(取消前的快照等)")

await agent3.aclose()

# %% [markdown]
# 取消后流**干净地结束**(不抛异常)——`_iter_until_cancelled` 在取消分支直接 `return`。
# `manager.cancel(agent_id, thread_id)`(`manager.py:422`)会同时设 manager 级与 agent 级事件,
# `/stop` 斜杠命令走的也是这条路。
#
# ## 7. 协议层:同一个图,三种出口
#
# `protocols/` 注册表里有三种协议,决定 `call/stream` 的**出入口形态**:
#
# | 协议 | 出口形态 | 适用 |
# |------|----------|------|
# | `langgraph`(默认) | 结构化事件(本本所见的 `AgentEventType`) | 宿主自绘 UI |
# | `openai` | OpenAI `ChatCompletionChunk` 流 | OpenAI 兼容网关 |
# | `mcp` | MCP `SamplingMessage` | MCP 客户端宿主 |
#
# 注意 `stream_events()`(`agent.py:548`)**刻意不做斜杠拦截**——它是给宿主转发原始事件用的透传口。
#
# ## 8. `aget_history` 的快路径
#
# 每条新消息都被盖上 `checkpoint_ts`(`CheckpointTsMiddleware`);`aget_history`
# 先比较"最后已知时间戳"与最新检查点,能增量就不全扫(`agent.py:571`)。数据量大时这是关键优化。

# %%
hist = await agent2.aget_history("s1")
for m in hist:
    ts = m.additional_kwargs.get("checkpoint_ts")
    print(f"  {type(m).__name__:14s} ts={ts}  {str(m.content)[:40]!r}")

await agent2.aclose()
print("\n(两个 agent 已关闭;工作区保留在 learning/.workspaces/ 供检查)")

# %% [markdown]
# ## 9. 思考题
#
# 1. 取消费"赛跑"而不是"块间查标志"——若换成后者,什么场景下 `/stop` 会失灵?
# 2. 为什么 `stream_events()` 不做斜杠拦截?如果它也拦,会发生什么矛盾?
# 3. thread_id 由调用方指定;`ChatRequest` 里 `thread_id` 缺省时会自动生成 uuid——想想宿主(IM 网关)应按什么粒度分配 thread?
# 4. 本轮 `call()` 返回的 `messages` 只含**新增**消息,完整历史要靠 `aget_history`——为什么不直接返回全量?
#
# ## 10. 延伸阅读
#
# - `slash/handlers.py` —— /stop /model /skills 的实现
# - `tests/test_agent*.py`、`tests/slash/` —— 行为契约
# - `examples/11_multi_agent.py`(需 Key)—— manager 的注册/路由/取消实战
# - 下一本:[04_middleware_pipeline.ipynb](04_middleware_pipeline.ipynb) —— 中间件链的顺序哲学
