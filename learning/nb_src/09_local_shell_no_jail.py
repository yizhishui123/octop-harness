# %% [markdown]
# # 09 · 沙箱一:无监禁的启发式翻译(macOS / 无 bwrap / 宿主根)
#
# **学习目标**
#
# - 理解**两级沙箱策略**:Linux + bwrap 有真监禁(10 本);其余平台走"保守的可信路径翻译";
# - 亲手验证 `map_virtual_abs_path` 的**可信度规则**:工作区内 / 有现存祖先 / 其余不动;
# - 观察**双向改写**:进——命令里的虚拟路径映射到 `{root_dir}/…`;出——输出里的 root 前缀还原成 `/…`;
# - 端到端复现 AGENTS.md §7 的经典图:`write_file("/gen/...")` + `execute(...)` + 读回产物。
#
# 本本实验在你的机器上**真实执行**(macOS 路径;Linux 无 bwrap 时同理)。
# 源码:`backends/local_shell.py`。

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

def show(path: str, start: int, end: int) -> None:
    """带行号打印仓库内源码片段"""
    lines = (REPO / path).read_text(encoding="utf-8").splitlines()
    for i in range(start - 1, min(end, len(lines))):
        print(f"{i + 1:5d} │ {lines[i]}")

from octop_harness.backends import resolve_backend
from octop_harness.backends.bwrap_shell import resolve_bubbled_bwrap
from octop_harness.backends.local_shell import (
    map_virtual_abs_path,
    present_host_paths_in_output,
    rewrite_virtual_paths_in_command,
)

print("ok, 仓库根:", REPO)

# %% [markdown]
# ## 1. 两级策略与门控
#
# 工厂只在 **Linux + virtual_mode + 非宿主 root + bwrap 在 PATH** 四条同时满足时才选
# `BubbledLocalShellBackend`;否则退到 `HarnessLocalShellBackend`(本本主角):

# %%
gate = resolve_bubbled_bwrap(virtual_mode=True, root_dir="/tmp/some-root")
print(f"本机 bwrap 门控结果:{gate!r}(macOS 上恒为 None → 走 HarnessLocalShellBackend)")

# %%
BASE = Path(tempfile.mkdtemp(prefix="nb09-")).resolve()
ROOT = BASE / "root"          # 虚拟 "/" 的宿主落点(非宿主根!)
WS = ROOT / "ws"              # 工作区(root 内)
WS.mkdir(parents=True)

backend = resolve_backend(
    {"type": "local_shell", "root_dir": ROOT, "virtual_mode": True},
    workspace_dir=WS,
    system_files_path="",
)
print("拿到的后端:", type(backend).__name__)

# %% [markdown]
# ## 2. 进:可信路径翻译的规则
#
# 没有监禁,凭什么敢把命令里的 `/gen/x` 改写成 `{root}/gen/x`?规则(`local_shell.py:68`)
# 按**证据强度**排序:
#
# 1. 已存在的宿主路径(工具链、`/tmp`、用户给的宿主路径)——**原样保留,宿主优先**;
# 2. 目标落在**配置的工作区**内——工作区就是证据;
# 3. 宿主拥有的顶层树(`/usr`、`/tmp` 等,即使末级不存在)——保留;
# 4. **现存祖先**:虚拟树里已有父目录存在(说明这棵虚拟树真的在用)——映射;
# 5. 其余——**宁可不映射**(命令会在"错误的地方"失败,也好过偷偷改写)。

# %%
show("src/octop_harness/backends/local_shell.py", 68, 92)

# %%
(ROOT / "gen").mkdir()   # 先造出"现存祖先"

cases = [
    ("/usr/local/bin/tool", "宿主顶层树(即使不存在)"),
    ("/etc/hosts", "已存在的宿主路径"),
    (f"{WS}/notes/a.md", "工作区内的虚拟绝对路径"),
    ("/gen/out.txt", "有现存祖先 {root}/gen"),
    ("/no-such-tree/x.txt", "毫无证据的虚拟路径"),
]
for path, why in cases:
    mapped = map_virtual_abs_path(path, ROOT, workspace_dir=WS)
    changed = "→ 映射" if mapped != path else "= 不动"
    print(f"{changed}  {path}\n        ({why})\n        {mapped if changed == '→ 映射' else ''}")

# %% [markdown]
# ## 3. 进:整条命令的改写
#
# `rewrite_virtual_paths_in_command` 用正则扫描命令里的绝对路径 token
# (裸 token 遇 `:` 停——PATH 列表逐段处理;引号内的也认;**只给 root 前缀加引号**,
# 后缀里的 glob 继续可展开):

# %%
for cmd in (
    "cat /gen/out.txt",
    "PATH=/gen/bin:/usr/bin env",
    "echo \"/gen/out.txt\" > /gen/log.txt",
    "curl -s https://example.com/gen/out.txt",   # URL 里的路径不该被动
):
    print(f"$ {cmd}")
    print(f"  → {rewrite_virtual_paths_in_command(cmd, ROOT, workspace_dir=WS)}\n")

# %% [markdown]
# ## 4. 出:输出还原
#
# 命令输出的宿主路径要**还原成 agent 视角**,否则模型看到的 `pwd` 是一长串临时目录,
# 与它自己的路径世界观冲突:

# %%
sample_output = f"written to {ROOT}/gen/out.txt (cwd={WS})"
print("模型看到的输出:", present_host_paths_in_output(sample_output, ROOT))

# %% [markdown]
# ## 5. 端到端:AGENTS.md §7 的那张图
#
# ```text
# model: write_file("/gen/run.sh") + execute("sh /gen/run.sh")
#         │                              │
#         ▼                              ▼
#   deepagents → {root}/gen/run.sh     命令改写:虚拟路径 → {root}/gen/...
#                                      脚本以工作区为 cwd 执行,产物落 {root}/ws/
# model/harness 读回产物:
#   materialize_local 相对路径回退(06 本的回退链)
# ```

# %%
# ① 模型视角:通过 backend 协议写"虚拟路径"(deepagents 会拼到 root 下)
#    注意脚本内部用**相对路径**输出——命令改写只作用于命令字符串本身,
#    不递归进入脚本内容;而 execute 的 cwd 已对齐工作区,相对路径天然落对地方。
backend.write("/gen/run.sh", 'echo "产物来自工作区 cwd" > out.txt\n')

# ② execute:命令里的 /gen/run.sh 被自动映射到 {root}/gen/run.sh
r = backend.execute("sh /gen/run.sh")
print("execute exit_code:", r.exit_code)

# ③ 产物落在哪?cwd 对齐工作区 → {root}/ws/out.txt
produced = WS / "out.txt"
print("产物位置:", produced.relative_to(BASE))
print("产物内容:", produced.read_text().strip())

# ④ pwd 证明:cwd 对齐工作区,且输出被还原成 agent 视角
print("pwd 输出:", backend.execute("pwd").output.strip())

# %% [markdown]
# 两个关键事实:
#
# 1. **`pwd` 打印 `/ws`**——宿主的 `{root}/ws` 被还原了。模型的世界自洽:它以为自己在 `/ws`,
#    文件在 `/gen/`,宿主的一切都藏在翻译层后面。
# 2. **改写不递归**:`sh /gen/run.sh` 里的命令 token 会被映射,但脚本**内容**里的 `/gen/out.txt`
#    原样交给宿主 shell(在真宿主 `/gen` 上写,会失败/越权)。所以生成脚本的提示词约定是:
#    脚本内部用相对路径(cwd 已对齐),或显式模式(§6)下让模型先调 `virtual_to_native_path`。
#
# ## 6. `explicit_virtual_paths`:另一种信任模型(Windows 子树专家)
#
# 还有一条极端路线:`explicit_virtual_paths=True` 时**完全不做命令扫描改写**,
# 改为给模型一个 `virtual_to_native_path` 工具 + 一段提示词契约:
# "execute 不改写;先把虚拟路径交给工具换原生路径,再把原生路径喂给命令;永远别给文件工具盘符路径"。
# 适合路径形态固定、但宿主路径无法被静态推断的场景(Windows 子树专家)。

# %%
show("src/octop_harness/backends/explicit_virtual_path.py", 17, 26)

# %%
b_explicit = resolve_backend(
    {"type": "local_shell", "root_dir": ROOT, "virtual_mode": True},
    workspace_dir=WS,
    system_files_path="",
    explicit_virtual_paths=True,
)
r = b_explicit.execute("cat /gen/out.txt")   # 注意:不再改写 → 按宿主字面路径执行
print("explicit 模式下 exit_code:", r.exit_code, "| output 尾部:", repr(r.output[-60:]))

# %% [markdown]
# explicit 模式下 `cat /gen/out.txt` 失败(exit_code 非零)——因为命令被**原样**交给宿主 shell,
# `/gen` 在宿主上并不存在。这就是"信任模型自己翻译"的含义:模型必须先调
# `virtual_to_native_path("/gen/out.txt")` 拿到 `{root}/gen/out.txt` 再用。
#
# ## 7. 思考题
#
# 1. 规则 5("宁可不映射")的失败模式是什么?模型会怎么自我修复?
# 2. 为什么 `_quote_mapped_bare_path` 只给 root 前缀加引号?(提示:`echo /gen/*.txt` 里的 `*` 谁来展开)
# 3. 输出还原只处理 root 前缀;如果命令打印了工作区外的宿主路径(如 `/etc/hosts`)会怎样?该怎样吗?
# 4. `execute` 以宿主 shell 跑命令(`shell=True`),安全边界在哪一层?(提示:14 本的 FilesystemGuard / ToolGuard)
#
# ## 8. 延伸阅读
#
# - `tests/test_bwrap_shell.py`(跨平台部分:改写规则的表驱动测试)
# - `backends/local_shell.py` 全文——本本只覆盖了翻译核心
# - 下一本:[10_bwrap_jail.ipynb](10_bwrap_jail.ipynb) —— Linux 上的真监禁

# %%
shutil.rmtree(BASE, ignore_errors=True)
print("临时目录已清理")
