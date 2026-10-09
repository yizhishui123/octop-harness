# %% [markdown]
# # 08 · 后端工厂与云存储
#
# **学习目标**
#
# - 吃透 `resolve_backend` 工厂:spec 四种形态、内置类型表、root_dir/virtual_mode/workspace_dir 的交互规则;
# - 理解 **composite artifacts 包装**:宿主根场景下 deepagents 卸载为什么要被"改道";
# - 认识云后端(COS/S3/OSS/OBS/Postgres)的**嵌套键编址** `/.octop/workspaces/<id>/…`;
# - 玩一下 `state` 后端与 `probe_backend`(全离线)。
#
# 源码:`backends/__init__.py`(工厂)、`backends/composite.py`、`backends/cloud_storage_base.py`。

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

from octop_harness.backends import resolve_backend, spec_supports_execution

print("ok, 仓库根:", REPO)

# %% [markdown]
# ## 1. spec 的四种形态
#
# ```text
# None            → DEFAULT_BACKEND_SPEC(local_shell + root_dir="/" + virtual_mode=True)
# "state"         → {"type": "state"}(字符串直接当类型名)
# {"type": ...}   → 类型 + 逐类型 kwargs
# BackendProtocol 实例 → 原样返回(鸭子检查:有 read/write/ls/edit/glob/grep)
# ```
#
# 内置类型(`_BUILTIN_TYPES`):`local_shell`(默认)、`filesystem`、`state`、`store`、`composite`、
# `s3`、`postgres`、`cos`、`oss`、`obs`、`docker`、`opensandbox`。

# %%
show("src/octop_harness/backends/__init__.py", 74, 92)

# %%
BASE = Path(tempfile.mkdtemp(prefix="nb08-")).resolve()
WS_DIR = BASE / "ws"
WS_DIR.mkdir()

# 形态一:spec 不固定 root_dir → 与 workspace 对齐(推荐形态)
b1 = resolve_backend({"type": "filesystem"}, workspace_dir=WS_DIR, system_files_path=".octop")
print("对齐形态:", type(b1).__name__, "| root:", b1.root_dir, "| virtual:", b1.virtual_mode)

# 形态二:默认 spec(= None)→ 宿主根 + composite 包装
b2 = resolve_backend(None, workspace_dir=WS_DIR, system_files_path=".octop")
print("默认形态:", type(b2).__name__, "| root:", getattr(b2, "root_dir", "?"))

# 形态三:现成实例 → 原样返回
from deepagents.backends import StateBackend
instance = StateBackend()
b3 = resolve_backend(instance, workspace_dir=WS_DIR, system_files_path=".octop")
print("实例透传:", b3 is instance)

# %% [markdown]
# ## 2. composite artifacts 包装:谁在保护你的 `/`
#
# 默认形态得到的类型是 `MountedCompositeBackend`——**composite**:
# 工厂在宿主根场景把本地 backend 包一层,设 `artifacts_root`,让 deepagents 的
# 会话历史 / 媒体卸载落进 `{workspace}/{system_files_path}`(如 `.octop/`),
# 而不是泼到 `/` 或 `~/` 一地。

# %%
show("src/octop_harness/backends/__init__.py", 258, 285)

# %% [markdown]
# 规则速记:
#
# - spec 没固定 root_dir → root=workspace,**无需**包装(卸载天然在工作区里);
# - root 是宿主 `/` → 包装,卸载改道进工作区;
# - 云后端无视 root_dir,有自己的编址(见 §4);
# - composite 的子后端用 `_scope_host_artifacts=False` 解析,避免**双层包装**。
#
# ## 3. `spec_supports_execution`:不实例化就能问"能不能跑命令"
#
# 安全策略接线处要用它决定走哪条文件系统守卫路径(14 本细讲):

# %%
for spec in (
    None,                                        # 默认 local_shell
    {"type": "filesystem"},
    {"type": "docker"},
    {"type": "opensandbox"},
    {"type": "state"},
    {"type": "composite", "default": {"type": "filesystem"}, "routes": {}},
):
    print(f"spec={str(spec)[:60]:60s} → execution={spec_supports_execution(spec)}")

# %% [markdown]
# ## 4. 云后端:嵌套键编址
#
# COS/S3/OSS/OBS/Postgres 都继承 `CloudStorageBackend`(由约 10 个存储原语实现的模板)。
# 关键设计:每个工作区的内容都嵌套在 **`/.octop/workspaces/<name>/…`** 虚拟目录下——
# 这样对象存储的"根"列出来是一个个文件夹,而不是一堆散文件;
# 同时**宿主家目录路径绝不泄漏进对象键**(`workspace.py:335` 的警告)。
#
# 读取时还有**旧版扁平键回退**:先试嵌套键 `/.octop/workspaces/x/SOUL.md`,
# 缺失再试旧键 `/SOUL.md`(升级平滑)。

# %%
show("src/octop_harness/backends/workspace.py", 330, 345)
print("……")
show("src/octop_harness/backends/workspace.py", 583, 600)

# %% [markdown]
# ## 5. `state` 后端的陷阱 + BackendProtocol 统一性
#
# 先看一个**真实陷阱**:`state` 后端把文件存在 LangGraph 状态里,所以它**只能在图执行内**读写——
# 在 notebook 里裸调它的 write 会直接被拒(错误信息还很贴心地告诉你正确姿势):

# %%
from deepagents.backends import StateBackend

sb = StateBackend()
try:
    sb.write("/hello.txt", "x")
except RuntimeError as e:
    print("state 后端拒绝裸调用 →", str(e)[:120], "…")

# %% [markdown]
# 协议统一性换 `filesystem` 后端验证(同样的代码面,换个 `type` 就换存储):

# %%
fs_dir = BASE / "fs"
fs_dir.mkdir()
fb = resolve_backend({"type": "filesystem", "root_dir": fs_dir, "virtual_mode": True},
                     workspace_dir=fs_dir, system_files_path="")

r = fb.write("/hello.txt", "filesystem 后端的内容")
print("write error:", r.error)
rd = fb.read("/hello.txt")
print("read:", rd.file_data["content"] if rd.file_data else None)
ls = fb.ls("/")
entries = getattr(ls, "entries", ls) or []
names = [e.get("path") if isinstance(e, dict) else getattr(e, "path", e) for e in entries]
print("ls('/'):", names[:5])

# %% [markdown]
# ## 6. `probe_backend`:写→读→删 探活
#
# 宿主配了一个陌生后端,先探一下再上 agent:

# %%
from octop_harness.backends import probe_backend

result = probe_backend({"type": "filesystem", "root_dir": fs_dir, "virtual_mode": True})
print("probe:", result)

# %% [markdown]
# ## 7. S3 兼容与 COS 的关系(选读)
#
# `S3Backend` 直接讲 deepagents 0.7 协议(第三方 `deepagents-backends` 的 S3 实现只到
# 0.5/0.6,刻意不用——`backends/__init__.py:469` 有注释);COS 在缺 SDK 时退化为
# S3 兼容探测(`cos_spec_to_s3_compat`)。云后端的依赖全部走 extras(`object-storage`),
# 缺包时报错会告诉你装什么(fail-soft 给体验,不给检查)。
#
# ## 8. 思考题
#
# 1. 为什么"对齐形态"(root=workspace)不需要 composite 包装?画一下两种形态下 deepagents 卸载路径分别落在哪。
# 2. 嵌套键 `/.octop/workspaces/<id>/` 的 `<id>` 用 agent_id 还是工作区名?多 agent 共享一个 bucket 时怎么避免踩脚?
# 3. `spec_supports_execution` 为什么不直接实例化再 hasattr 检查?(提示:构造副作用——docker 容器、远程连接)
# 4. 如果让你新增一个 Git 后端(文件即 commit),`CloudStorageBackend` 的十个原语里哪些可以复用?
#
# ## 9. 延伸阅读
#
# - `backends/cloud_storage_base.py` —— 存储原语模板
# - `tests/test_s3_compat.py`、`tests/test_cos_backend.py` —— 云后端测试(mock,无网络)
# - 下一模块:[09_local_shell_no_jail.ipynb](09_local_shell_no_jail.ipynb) —— 沙箱三部曲之一

# %%
shutil.rmtree(BASE, ignore_errors=True)
print("临时目录已清理")
