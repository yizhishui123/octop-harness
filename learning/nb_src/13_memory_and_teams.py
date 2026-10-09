# %% [markdown]
# # 13 · 记忆系统与 Teams 协作
#
# **学习目标**
#
# - 吃透记忆的 **L0-L3 分层**(原始事件 → 候选 → 原子/实体 → 摘要)与两种抽取触发;
# - 理解 **recall 快照/重放**:召回内容如何进提示却不污染 checkpoint;
# - 现场看会话 JSONL 与记忆工具;
# - 跑通 **Teams**:同一 manager 里两个 agent 通过 `ask_agent` 工具同步协作(离线)。
#
# 源码:`memory/runtime.py`、`memory/store.py`、`middleware/memory.py`、`teams/`。

# %%
# —— 标准前置(每本 notebook 自带,便于独立阅读)——
import asyncio
import shutil
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

from octop_harness import HarnessAgent, HarnessAgentConfig, HarnessAgentManager, init_workspace
from octop_harness.request import ChatRequest

from learning.support.fake_model import FakeChatModelFactory, FAKE_MODEL_REF, fake_providers

import logging
logging.getLogger("deepagents.middleware.skills").setLevel(logging.ERROR)

print("ok, 仓库根:", REPO)

# %% [markdown]
# ## 1. L0-L3:记忆的分层流水线
#
# `MemoryRuntime`(`memory/runtime.py:36`)包着 octop-memory 的 `Memory` + `MemoryService`:
#
# | 层 | 内容 | 谁写入 | 需要真 LLM? |
# |----|------|--------|--------------|
# | L0 | raw_events:用户可见的对话转写(触发语 + 最终回复,不含工具轮) | `MemoryMiddleware.after_model` 后台线程 | **否**(07 本见过它离线落库) |
# | L1 | episodes/candidates:从 L0 抽取的候选事实 | 抽取 LLM | 是 |
# | L2 | atoms/entities:提升后的原子事实与实体 | 抽取 LLM | 是 |
# | L3 | digests/entity_pages:周期摘要 | 维护定时器 + LLM | 是 |
#
# 抽取触发二选一:`idle`(默认,会话静止 300 秒的看门狗)或 `interval`(每 6 小时扫一次);
# 维护(瘦身/去重)每小时(`maintenance_interval=3600`)。中间件实例有**复用守卫**,
# 图重编译不会泄漏重复定时器(`runtime.py:144-161`)。
#
# L0 的"只记用户可见转写"很讲究:工具轮的中间态不进记忆,避免污染长期事实。

# %%
show("src/octop_harness/middleware/memory.py", 259, 268)

# %% [markdown]
# ## 2. recall:快照与重放
#
# 召回(retrieve)发生在 `before_model`——**每条新 HumanMessage 只做一次快照**;
# `wrap_model_call` 在**发给 API 的副本**上重放召回内容;checkpoint 里存的 state **不变**
# (`request.override(messages=...)` 只改本次请求)。这保证:同一 thread 重放/恢复时,
# 召回是"当时的快照"而不是"现在的检索结果"——可复现性优先。

# %%
show("src/octop_harness/middleware/memory.py", 282, 296)

# %% [markdown]
# ## 3. 会话 JSONL 与记忆工具
#
# 除了 memory.sqlite,还有按天滚动的 `sessions/YYYY-MM-DD.jsonl`(默认 50MB 轮转):

# %%
# 造一个带记忆的 agent 跑一轮(复用 07 的结论:L0 离线就能落库)
WS = WORKSPACES / "nb13"
if WS.exists():
    shutil.rmtree(WS)
init_workspace(WS, language="zh")

cfg_mem = HarnessAgentConfig(
    workspace_dir=WS, providers=fake_providers(), default_model=FAKE_MODEL_REF,
    memory_enabled=True, web_search_tools=False,
)
agent_mem = HarnessAgent(cfg_mem, model_factory=FakeChatModelFactory(["我记住了:你偏好简洁回答。"]))
await agent_mem.call(ChatRequest(messages="请记住我偏好简洁回答", thread_id="mem1", user="learner"))
await asyncio.sleep(0.5)     # 给 L0 后台线程时间
await agent_mem.aclose()

jsonl = next((WS / "sessions").glob("*.jsonl"), None)
print("会话 JSONL:", jsonl.name if jsonl else None)
if jsonl:
    print(" 首行(截断):", jsonl.read_text().splitlines()[0][:200], "…")

# %% [markdown]
# 模型可用的两个记忆工具(`builtin/tools/memory_tools.py`):
# `memory_search(query, max_results)`——service 的排序器融合 atom/page/raw 三路召回;
# `memory_get(path)`——取某条记忆的原文。
#
# ## 4. Teams:收件箱驱动的 agent 间协作
#
# `TeamManager(registry)` 提供同侪发现与调用;`PeerAgentMiddleware`(04 本 15 号位)挂上
# `agent_list` / `ask_agent` 两个工具,并在消息里出现 `@agent` 提及时把同侪名单追加到
# **提示后缀**(前缀保持供应商缓存友好)。
#
# `ask_agent` 两种模式:
#
# - `sync`:当场调用目标 agent,结果作为 ToolMessage 返回;
# - `background`:投递到 **inbox**,宿主的 `TeamProcessor.compose_followup` 组装追问,
#   在**源线程**上追加一轮调用,再由 `TeamProcessor.on_reply` 推送(ReplyEvent)。
#   harness 只定义 Protocol,怎么推给用户(IM/DM)是宿主的事——库/应用边界的又一例。

# %%
WS_A = WORKSPACES / "nb13a"
WS_B = WORKSPACES / "nb13b"
for w in (WS_A, WS_B):
    if w.exists():
        shutil.rmtree(w)
    init_workspace(w, language="zh")

def team_cfg(ws: Path) -> HarnessAgentConfig:
    return HarnessAgentConfig(
        workspace_dir=ws, providers=fake_providers(), default_model=FAKE_MODEL_REF,
        memory_enabled=False, web_search_tools=False,
    )

mgr = HarnessAgentManager(providers=fake_providers())
# 共享脚本队列按"谁先开口谁消耗"出队:leader 的 tool_call → helper 的回答 → leader 的总结
mgr._shared_factory = FakeChatModelFactory([
    AIMessage(content="", tool_calls=[{
        "name": "ask_agent",
        "args": {"expert": "helper", "message": "帮我算 1+1", "mode": "sync"},
        "id": "call_1",
    }]),
    "1+1 = 2(helper 计算)。",
    "helper 告诉我:结果是 2。",
])
mgr.create_agent(team_cfg(WS_A), agent_id="leader")
mgr.create_agent(team_cfg(WS_B), agent_id="helper")
print("同侪名单:", [e.agent_id for e in mgr.list_agents()])

# %%
# 离线跑通一次 sync 协作(note:ask_agent 需要 user 做会话归属)
res = await mgr.call("leader", ChatRequest(
    messages="让 helper 帮我算 1+1", thread_id="team1", user="learner",
))
print("leader 线程里的消息流:")
for m in res["messages"]:
    text = str(m.content).replace("\n", " ")
    print(f"  {type(m).__name__:12s} {text[:100]}")

await mgr.aremove_agent("leader")
await mgr.aremove_agent("helper")

# %% [markdown]
# 看清楚这条链:leader 的模型(第 1 条脚本)发起 `ask_agent` 工具调用 →
# 工具内部调用 helper(第 2 条脚本成了 helper 的回复)→ 结果以结构化 ToolMessage 回到
# leader 的线程 → leader 的模型(第 3 条脚本)总结给用户。**两个 agent、一个共享工厂、零网络。**
#
# inbox(background 模式)的关键设计(`teams/inbox.py`):
# 进程级 `asyncio.Queue`,最多 `max_concurrency=8` 并发;**按目标加锁**——同一个被叫者
# 串行、不同被叫者并行;按源加锁串行化追问。状态机:queued → running → replying → done/failed/cancelled。
# 完整示例见 `examples/12_team_inbox_push.py`(需 Key)。
#
# ## 5. 热重建时的记忆存活
#
# `manager.rebuild_all_agents` / `set_security_policy` 会拆掉重建所有 agent——
# 记忆连接不能跟着拆。`memory/store.py` 的 `SharedMemoryStore` 用
# `MemoryIdentity(namespace, backend, location)` 做键、引用计数管理进程级 `Memory` 实例,
# 全部 agent 释放后才真正关闭(防 `psycopg_pool.PoolClosed`)。07 本已见过它的"一库两用"。
#
# ## 6. 思考题
#
# 1. L0 只记"用户可见转写"——如果工具轮里发现了重要事实,它该怎么进记忆?
# 2. recall 用"快照重放"而非"实时检索",牺牲了什么换到了什么?
# 3. inbox 的"按目标锁"为什么必要?两个 job 同时写同一个 helper 的线程会发生什么?
# 4. `ask_agent` 的 sync 模式嵌套在工具调用里——如果 helper 卡住,leader 的整轮都会卡住。怎么破?(提示:mode="background"、超时、取消)
#
# ## 7. 延伸阅读
#
# - `tests/test_memory_*.py`、`tests/teams/`、`tests/test_peer*.py`
# - `multi_agent_demo/` —— 三个人设工作区(SOUL/IDENTITY/HEARTBEAT…)的完整语料
# - 下一本:[14_security_stack.ipynb](14_security_stack.ipynb)
