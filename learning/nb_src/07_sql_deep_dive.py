# %% [markdown]
# # 07 · SQL 深潜:三个落点
#
# **学习目标**
# - 澄清一个常见误解:这个库**没有 ORM、没有业务数据库**;SQL 只出现在三个 persistence 落点;
# - 落点一:LangGraph checkpointer(`checkpoints.sqlite`,AsyncSqliteSaver);
# - 落点二:octop-memory(`memory.sqlite`)——以及它**兼任 checkpointer** 的"一库两用";
# - 落点三:Postgres 文件后端(`backends/postgres.py`)——仓库里**唯一的手写 SQL**;
# - 全程用 `sqlite3` 现场开库看表,不做纸面推演。
#
# 实验全部离线(假模型 + sqlite 本地文件)。

# %%
# —— 标准前置(每本 notebook 自带,便于独立阅读)——
import shutil
import sqlite3
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

from octop_harness import HarnessAgent, HarnessAgentConfig, init_workspace
from octop_harness.request import ChatRequest

from learning.support.fake_model import FakeChatModelFactory, FAKE_MODEL_REF, fake_providers

import logging
logging.getLogger("deepagents.middleware.skills").setLevel(logging.ERROR)

def db_tables(path: Path) -> dict[str, int]:
    con = sqlite3.connect(path)
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    finally:
        con.close()

print("ok, 仓库根:", REPO)

# %% [markdown]
# ## 0. 全景:SQL 在这个库里的三个落点
#
# | 落点 | 位置 | SQL 来源 | 形态 |
# |------|------|----------|------|
# | ① LangGraph 检查点 | `{workspace}/checkpoints.sqlite` | langgraph-checkpoint-sqlite 包(核心依赖) | AsyncSqliteSaver |
# | ② 记忆系统 | `{workspace}/memory.sqlite` | octop-memory 包 | Memory(同时是 checkpointer!) |
# | ③ Postgres 文件后端 | 用户自己的 PG 库 | `backends/postgres.py` **手写 SQL** | JSONB 文件行 |
#
# 除此之外 `sqlite3` 只在一处被 import:把 `sqlite3.Error` 放进容错异常元组(`backends/utils.py:32`)。
#
# 选择链(`agent.py:1788` `_resolve_checkpointer`):
#
# ```text
# checkpointer=False(显式关)→ 用户实例 → memory 开启时复用 Memory 实例 → 默认 AsyncSqliteSaver
# ```

# %%
# 场景 A:memory 关闭 → 默认 AsyncSqliteSaver
WS_A = WORKSPACES / "nb07a"
if WS_A.exists():
    shutil.rmtree(WS_A)
init_workspace(WS_A, language="zh")

cfg_a = HarnessAgentConfig(
    workspace_dir=WS_A, providers=fake_providers(), default_model=FAKE_MODEL_REF,
    memory_enabled=False, web_search_tools=False,
)
agent_a = HarnessAgent(cfg_a, model_factory=FakeChatModelFactory(["第一轮。", "第二轮。"]))

t = "sql-a"
await agent_a.call(ChatRequest(messages="第一问", thread_id=t))
await agent_a.call(ChatRequest(messages="第二问", thread_id=t))
await agent_a.aclose()

ckpt = WS_A / "checkpoints.sqlite"
print("checkpoints.sqlite 存在:", ckpt.exists())
tables = db_tables(ckpt)
for name, n in tables.items():
    print(f"  {name:22s} {n} 行")

# %% [markdown]
# 标准的 langgraph checkpointer 三件套:
# - `checkpoints`:每个 thread 每轮一条,`parent_checkpoint_id` 串成链(时间旅行/回放靠它);
# - `checkpoint_blobs`:消息内容的去重存储(按 digest);
# - `checkpoint_writes`:每轮的增量写(channel/idx)。
#
# 看一眼 checkpoint 行的关键列,直观感受"链":

# %%
con = sqlite3.connect(ckpt)
rows = con.execute(
    "SELECT thread_id, checkpoint_id, parent_checkpoint_id FROM checkpoints ORDER BY rowid"
).fetchall()
con.close()
for r in rows:
    parent = (r[2] or "NULL")[:8]
    print(f"  thread={r[0]}  ckpt={r[1][:8]}…  parent={parent}")

# %% [markdown]
# **工程细节**(`agent.py:1822-1834`):默认路径用 `AsyncSqliteSaver`,其 aiosqlite 工作线程被标记为
# **daemon**(进程退出不被它卡住);同步构造时 `AsyncSqliteSaver.__init__` 要求运行中的事件循环,
# `_build_async_sqlite_saver`(`agent.py:1931`)为此专门起了一个一次性循环。
#
# ## 1. 场景 B:memory 开启 → memory.sqlite 一库两用

# %%
WS_B = WORKSPACES / "nb07b"
if WS_B.exists():
    shutil.rmtree(WS_B)
init_workspace(WS_B, language="zh")

cfg_b = HarnessAgentConfig(
    workspace_dir=WS_B, providers=fake_providers(), default_model=FAKE_MODEL_REF,
    memory_enabled=True, web_search_tools=False,
)
agent_b = HarnessAgent(cfg_b, model_factory=FakeChatModelFactory(["记住:我喜欢 sqlite。"]))

await agent_b.call(ChatRequest(messages="请记住我喜欢 sqlite", thread_id="sql-b"))
import asyncio
await asyncio.sleep(0.5)   # 给 L0 落库的守护线程一点时间
await agent_b.aclose()

files = sorted(p.relative_to(WS_B) for p in WS_B.iterdir())
print("工作区顶层:", [str(f) for f in files])

# %% [markdown]
# **布局教学点**:`system_files_path` 默认空串(legacy),产物直接落在工作区根;
# 设成 `".octop"` 则收纳进子目录。看看两种布局的差别(下面这行如果报"不存在",
# 说明你的仓库版本默认布局已变——以 `memory/store.py` 的 `db_path` 逻辑为准):

# %%
mem = WS_B / "memory.sqlite"
print("checkpoints.sqlite 出现了吗?", (WS_B / "checkpoints.sqlite").exists(), "(预期 False——被 Memory 兼任了)")
tables = db_tables(mem)

ckpt_like = {k: v for k, v in tables.items() if k in ("checkpoints", "writes", "hm_checkpoint_blobs")}
mem_like = {k: v for k, v in tables.items() if k.startswith("octop_harness_") and not any(
    x in k for x in ("_fts", "_config", "_data", "_docsize", "_idx"))}
print("\n【checkpointer 侧的表】(与场景 A 同构 → 一库两用)")
for k, v in ckpt_like.items():
    print(f"  {k:22s} {v} 行")
print("\n【记忆侧的业务表】(部分)")
for k, v in sorted(mem_like.items()):
    print(f"  {k:38s} {v} 行")

# %% [markdown]
# 记忆侧的表族(0 行居多是正常的——L1-L3 抽取需要真 LLM;**L0 原始事件不需要**):

# %%
con = sqlite3.connect(mem)
row = con.execute(
    "SELECT host, thread_id, event_type, substr(content, 1, 40) FROM octop_harness_raw_events LIMIT 3"
).fetchall()
con.close()
for r in row:
    print("  L0 raw_event:", r)
print("\nFTS 全文索引表(如 octop_harness_raw_events_fts)与业务表成对出现——检索用,免 LIKE 扫全表。")

# %% [markdown]
# 为什么要"一库两用"?看 `memory/store.py` 的模块说明:进程级的 `SharedMemoryStore` 用
# 引用计数缓存 `Memory` 实例(`MemoryIdentity(namespace, backend, location)` 为键),
# 专门为了**热重建 agent 时连接池不被拆掉**(否则会撞 `psycopg_pool.PoolClosed`)。

# %%
show("src/octop_harness/memory/store.py", 1, 14)

# %% [markdown]
# Postgres 记忆后端:配置 `memory_backend="postgres"` + DSN 即可,表结构同款由 octop-memory 管理。
#
# 顺带一提,同目录的 `sessions/YYYY-MM-DD.jsonl` 是会话转写(不是 SQL,属于运行时持久化):

# %%
jsonl = next((WS_B / "sessions").glob("*.jsonl"), None)
if jsonl:
    print(jsonl.name, "首行:")
    print(" ", jsonl.read_text().splitlines()[0][:160], "…")

# %% [markdown]
# ## 2. 落点三:Postgres 文件后端(仓库里唯一的手写 SQL)
#
# `backends/postgres.py`:`PostgresBackend(CloudStorageBackend)` 把文件存成 JSONB 行。
# 三个值得学的点:**标识符防注入**、**建表 DDL 与前缀索引**、**upsert 与前缀列目录**。

# %%
show("src/octop_harness/backends/postgres.py", 140, 150)   # _sql_ident:防注入正则

# %%
from octop_harness.backends.postgres import _sql_ident   # 纯函数,可离线调用

for ident in ("files", 'files; DROP TABLE users; --', 'weird"name'):
    try:
        print(f"_sql_ident({ident!r:32s}) → {_sql_ident(ident)!r}")
    except ValueError as e:
        print(f"_sql_ident({ident!r:32s}) → ValueError: {e}")

# %%
show("src/octop_harness/backends/postgres.py", 246, 268)   # _init_schema:DDL + 前缀索引

# %% [markdown]
# - `path text_pattern_ops` 前缀索引:配合 `LIKE 'prefix%'` 的目录列举走索引;
# - upsert:`INSERT ... ON CONFLICT (path) DO UPDATE`(同 path 覆盖写);
# - 列举:`LIKE` + `split_part` 取直接子项(模拟目录 ls)。
#
# 再看 DSN 解析的一个安全细节——**密码永远不回显**:

# %%
show("src/octop_harness/backends/postgres.py", 58, 66)

# %% [markdown]
# psycopg 是 `[remote-backends]` 可选 extra;未安装时 import 守卫给出明确指引(fail-soft 哲学)。
# 依赖它跑不起来的本机测试(`tests/test_postgres_spec.py`)只测 DSN 解析等纯逻辑,不碰真库。
#
# ## 3. 总结:SQL 落点决策树
#
# ```text
# 需要持久化什么?
#   ├─ 会话状态(消息/工具轮次)→ checkpointer
#   │     memory 开? → memory.sqlite / postgres(一库两用)
#   │     否         → checkpoints.sqlite(AsyncSqliteSaver)
#   ├─ 长期记忆(事实/实体/摘要)→ octop-memory 表族(sqlite 默认,postgres 可选)
#   └─ 把 PG 当"文件系统"用    → PostgresBackend(手写 SQL,JSONB 行)
# ```
#
# ## 4. 思考题
#
# 1. `Memory` 兼任 checkpointer 省了什么、赌了什么?(单点故障?锁竞争?备份粒度?)
# 2. langgraph 的 checkpoint 链(parent_id)支持时间旅行——结合 `aget_history` 的增量快路径,想想宿主"撤销到第 N 轮"怎么实现。
# 3. Postgres 后端为什么用 JSONB 存整文件而不是拆行存行?(提示:deepagents FileData 语义、读写粒度)
# 4. WAL 文件(`-wal`/`-shm`)被列进 `SYSTEM_FILE_NAMES`——备份工作区时漏掉它们会怎样?
#
# ## 5. 延伸阅读
#
# - `tests/test_memory_store.py`、`tests/test_postgres_spec.py`、`tests/test_agent.py`(checkpointer 相关)
# - `agent.py:1788-1951` —— checkpointer 解析与 sqlite 生命周期清理
# - 下一本:[08_backend_factory_and_cloud.ipynb](08_backend_factory_and_cloud.ipynb)
