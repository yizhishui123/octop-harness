# %% [markdown]
# # 06 · `BackendWorkspace`:L1 唯一 I/O 门面
#
# **学习目标**
#
# - 记住 L0-L3 分层与"哪类 I/O 走哪条路"的判定表——这是本仓库最重要的模块边界;
# - 亲手实验 `resolve_path` 速查表的每一行(相对 / 绝对 / `~` / 越界);
# - 体验 **materialize 多层回退**:`write_file("/gen/x") + execute(...)` 之后,内容怎么被读回来;
# - 认识 `backend_write_force`(绕过 deepagents"拒绝覆盖"护栏的正规姿势)。
#
# 源码:`backends/workspace.py`(门面)、`backends/utils.py`(L0 辅助)、`backends/__init__.py`(工厂,08 本细讲)。

# %%
# —— 标准前置(每本 notebook 自带,便于独立阅读)——
import shutil
import sys
import tempfile
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

from octop_harness.backends import resolve_backend
from octop_harness.backends.workspace import BackendWorkspace

print("ok, 仓库根:", REPO)

# %% [markdown]
# ## 1. 分层与"哪条路"判定表
#
# | 层 | 模块 | 职责 |
# |----|------|------|
# | L0 | `backends/utils.py` | 低层 I/O 辅助;`materialize_storage_path` 逃生口 |
# | L1 | `backends/workspace.py`(`BackendWorkspace`) | **agent 可见内容**的唯一 I/O 门面 |
# | L2 | `middleware/*`、`builtin/tools/*`、`init.py` | 业务/种子逻辑,经 L1 读写 |
# | L3 | `agent.py` | 纯组装 |
#
# **判定表**(背下来能省一半迷路时间):
#
# | I/O 内容 | 入口 |
# |----------|------|
# | 模板/bootstrap/skills/媒体/目录清单(agent 用得到的内容) | `agent.workspace`(BackendWorkspace)——**必须** |
# | LLM 的 `read_file`/`write_file` 工具 | `agent.backend`(deepagents 协议,由 virtual_mode/root_dir 解释) |
# | memory DB、`sessions/` JSONL、`checkpoints.sqlite` | 本地 FS / DB 驱动直连(显式例外:要真实 fd/锁/append) |
# | 运行时诊断日志 | `~/.octop-harness/logs`(进程级,非工作区) |
# | CLI 全局配置 | `~/.octop-harness/`(非工作区) |

# %%
show("src/octop_harness/backends/workspace.py", 356, 372)

# %% [markdown]
# 门面契约:`read_text` / `exists` **fail-soft**(返回 None/False);`write_text` / `upload_bytes` **抛异常**。
# 读错了不该炸流程,写错了必须让人知道——同样是"fail-soft 给体验"哲学。
#
# ## 2. 搭台:非宿主根 + virtual_mode 的经典场景
#
# 本本全部实验在这个布局上进行(root ≠ 宿主 `/`,`virtual_mode=True`):

# %%
BASE = Path(tempfile.mkdtemp(prefix="nb06-")).resolve()   # resolve:macOS 下 /var → /private/var
ROOT = BASE / "root"          # backend root_dir:虚拟 "/" 落在这
WS_DIR = ROOT / "ws"          # workspace_dir:agent 的推荐工作目录(在 root 内)
WS_DIR.mkdir(parents=True)

backend = resolve_backend(
    {"type": "filesystem", "root_dir": ROOT, "virtual_mode": True},
    workspace_dir=WS_DIR,
    system_files_path=".octop",
)
workspace = BackendWorkspace(backend, WS_DIR, system_files_path=".octop")
print("backend:", type(backend).__name__, "| root_dir:", backend.root_dir, "| virtual_mode:", backend.virtual_mode)

# %% [markdown]
# ## 3. `resolve_path` 速查表逐行实验
#
# | 输入 | 预期 |
# |------|------|
# | 相对 `AGENTS.md` | `{workspace_dir}/AGENTS.md` |
# | 绝对 `/SOUL.md` | virtual_mode → 映射到 `{root_dir}/SOUL.md` |
# | `~/x` | `expanduser()` 后的宿主路径 |
# | `../escape` | `PermissionError`(逃逸工作区) |

# %%
for frag in ("AGENTS.md", "/SOUL.md", "~/x.md"):
    print(f"resolve_path({frag!r:14s}) → {workspace.resolve_path(frag)}")

try:
    workspace.resolve_path("../escape.txt")
except PermissionError as e:
    print(f"resolve_path('../escape.txt') → PermissionError: {e}")

# %% [markdown]
# 绝对路径 `/SOUL.md` 落在 `{root}/SOUL.md`——**不是** `{workspace}/SOUL.md`!
# 相对路径才是工作区语义。这两个概念不分的 bug,在本库的历史上占了一半(AGENTS.md §7 专门警告)。
#
# ## 4. 走门面读写(经 backend 协议,不是直接 open)

# %%
workspace.write_text("notes/todo.md", "- 学完第 06 本\n", force=True)
print("read_text:", repr(workspace.read_text("notes/todo.md")))
print("实际落盘:", (WS_DIR / "notes" / "todo.md").read_text().strip())
print("exists('no-such.txt'):", workspace.exists("no-such.txt"), "(fail-soft,不抛)")

# %% [markdown]
# ## 5. materialize 多层回退:产物的"回家之路"
#
# 经典场景(AGENTS.md §7 的图):
#
# ```text
# model: write_file("/gen/run.py") + execute("… /gen/run.py")
#         │                            │
#         ▼                            ▼
#   deepagents → {root}/gen/run.py   (沙箱内以 /gen/... 视角执行)
# harness 随后读取产物:
#   workspace.materialize_local("/gen/out.txt")
#     → 先试 {root}/gen/out.txt(虚拟映射),再试原始宿主路径
# ```

# %%
# 模拟 deepagents/沙箱落盘:产物出现在 {root}/gen/ 下,而不是 workspace 下
GEN = ROOT / "gen"
GEN.mkdir(exist_ok=True)
(GEN / "out.txt").write_text("产物内容:42\n")

p1 = workspace.materialize_local("/gen/out.txt")
print("materialize('/gen/out.txt') →", p1.relative_to(BASE) if p1 else None)
print("读回内容:", p1.read_text().strip() if p1 else None)

# %%
# 相对路径回退:root 下没有,就退回 workspace 下找
(WS_DIR / "report.md").write_text("工作区里的相对产物\n")
p2 = workspace.materialize_local("report.md")
print("materialize('report.md') →", p2.relative_to(BASE) if p2 else None)

# 两处都没有 → None(fail-soft)
print("materialize('/gen/missing.txt') →", workspace.materialize_local("/gen/missing.txt"))

# %% [markdown]
# ## 6. `backend_write_force`:绕过"拒绝覆盖"护栏
#
# deepagents 的 `backend.write()` **拒绝覆盖已有文件**——这是给 LLM 写操作设的护栏
# (防手滑覆盖)。但 harness 自己的种子/同步逻辑常常需要覆盖,于是 L0 提供了正规姿势:
# 写失败就退回 `read + edit` 全量替换,内容一致时干脆 no-op。

# %%
show("src/octop_harness/backends/utils.py", 115, 128)

# %%
from octop_harness.backends.utils import backend_write_force

# 第一次写:正常路径
backend.write("/fresh.txt", "v1")
print("首次写入:", backend.read("/fresh.txt").file_data["content"] if backend.read("/fresh.txt").file_data else None)

# 直接再 write:被护栏拒绝(error 字段非空)
r = backend.write("/fresh.txt", "v2")
print("直接覆盖被拒:write_result.error =", repr(r.error)[:80])

# backend_write_force:read+edit 全量替换
backend_write_force(backend, "/fresh.txt", "v2-forced")
print("force 后内容:", backend.read("/fresh.txt").file_data["content"])
# 内容相同的 no-op 分支
backend_write_force(backend, "/fresh.txt", "v2-forced")
print("同内容 force:no-op,无异常")

# %% [markdown]
# ## 7. `_backend_storage_key`:给 deepagents 的"虚拟键"
#
# `skill_paths()` / `memory_paths()` 交给 deepagents Skills/Memory 中间件的是
# **agent 视角的虚拟键**,不是宿主路径拼接(`virtual_mode` 下不拼 `root_dir`)——
# 中间件拿着键找 backend 要内容,backend 自己做映射。

# %%
print("skill_paths:      ", workspace.skill_paths())
print("memory_paths():   ", workspace.memory_paths())
print("memory_paths 覆盖:", workspace.memory_paths(["AGENTS.md", "SOUL.md"]))

# %% [markdown]
# 对比:同样的信息,**宿主侧**物化走 `resolve_path`。两条路服务的对象不同
# (deepagents 中间件 vs 宿主 I/O)——这就是"同一个内容,两种寻址"的完整图景。
#
# ## 8. 系统文件名单与 `system_files_path` 规范化
#
# `SYSTEM_FILE_NAMES` 认得 `checkpoints.sqlite`、`memory.sqlite(-wal/-shm)` 这些
# "运行时持久化"文件——它们不是 agent 内容,删除工作区时要区别对待。
# `normalize_system_files_path` 只接受工作区相对片段:

# %%
from octop_harness.backends.workspace import SYSTEM_DIR_NAMES, SYSTEM_FILE_NAMES, normalize_system_files_path

print("SYSTEM_DIR_NAMES:  ", sorted(SYSTEM_DIR_NAMES))
print("SYSTEM_FILE_NAMES: ", sorted(SYSTEM_FILE_NAMES))
for bad in ("/abs", "..", "~/x"):
    try:
        normalize_system_files_path(bad)
        print(f"normalize({bad!r}): 意外通过")
    except ValueError:
        print(f"normalize({bad!r}): ValueError ✓")

# %% [markdown]
# ## 9. 思考题
#
# 1. 为什么 `write_text` 抛异常而 `read_text` 返回 None?(提示:谁在调用它们,失败各意味着什么)
# 2. `materialize_local` 的"绝对路径先试 root 映射再试原始路径"——什么后端形态会让"原始路径"命中?
# 3. 把 memory DB 改成经 `BackendWorkspace` 写会坏什么?(提示:WAL、锁、append)
# 4. `../` 越界在 `resolve_path` 被拒,但 `/xxx` 绝对路径却允许去 root 任何角落——这两个策略放在一起合理吗?
#
# ## 10. 延伸阅读
#
# - `tests/test_workspace.py` —— 门面契约的完整测试
# - AGENTS.md §5/§7 —— 判定表与路径模型的权威表述
# - 下一本:[07_sql_deep_dive.ipynb](07_sql_deep_dive.ipynb) —— 打开这些 sqlite 文件看个究竟

# %%
shutil.rmtree(BASE, ignore_errors=True)
print("临时目录已清理")
