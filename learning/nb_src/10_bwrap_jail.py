# %% [markdown]
# # 10 · 沙箱二:bwrap 监禁解剖(Linux 真隔离)
#
# **学习目标**
# - 理解 `BubbledLocalShellBackend` 的**门控条件**(Linux + virtual_mode + 非宿主 root + bwrap);
# - 逐段解剖 `build_bwrap_argv`:bind / ro-bind / dev / proc / tmpfs / chdir;
# - 看懂 **jail 内 cwd 对齐**(`pwd` 打印虚拟工作区路径)与 **skills 额外挂载**;
# - 了解优雅降级:bwrap 消失/启动失败时退回 09 本的翻译路径。
#
# 本机若是 macOS:监禁**不会真的执行**(这正是门控的意义),我们用纯函数 + `platform` 参数
# 做"解剖式"学习;Linux 读者可按提示真跑。
# 源码:`backends/bwrap_shell.py`。

# %%
# —— 标准前置(每本 notebook 自带,便于独立阅读)——
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

from octop_harness.backends.bwrap_shell import (
    BubbledLocalShellBackend,
    build_bwrap_argv,
    resolve_bubbled_bwrap,
)

print("ok, 仓库根:", REPO, "| 本机平台:", sys.platform)

# %% [markdown]
# ## 1. 门控:四个条件缺一不可
#
# `resolve_bubbled_bwrap`(`bwrap_shell.py:46`)是工厂的分流闸门。
# 关键设计:`platform` 与 `bwrap_path` 是**可注入参数**——测试与非 Linux 平台可以模拟:

# %%
print("真实门控(本机):", resolve_bubbled_bwrap(virtual_mode=True, root_dir="/tmp/some-root"))

# 用参数模拟 Linux + bwrap 存在,验证逻辑本身:
simulated = resolve_bubbled_bwrap(
    virtual_mode=True, root_dir="/tmp/some-root",
    platform="linux", bwrap_path="/usr/bin/bwrap",
)
print("模拟 Linux 门控:", simulated)

for label, kwargs in {
    "virtual_mode=False": dict(virtual_mode=False, root_dir="/tmp/x", platform="linux", bwrap_path="/usr/bin/bwrap"),
    "宿主根 root_dir": dict(virtual_mode=True, root_dir="/", platform="linux", bwrap_path="/usr/bin/bwrap"),
    "bwrap 缺失": dict(virtual_mode=True, root_dir="/tmp/x", platform="linux", bwrap_path=None),
}.items():
    print(f"  {label:20s} →", resolve_bubbled_bwrap(**kwargs))

# %% [markdown]
# ## 2. argv 解剖:一条监禁命令的全部家当
#
# `build_bwrap_argv`(`bwrap_shell.py:86`)是纯函数,本机也能拼出来:

# %%
BASE = Path(tempfile.mkdtemp(prefix="nb10-")).resolve()
ROOT = BASE / "root"
(ROOT / "ws").mkdir(parents=True)

argv = build_bwrap_argv(
    bwrap="/usr/bin/bwrap",
    root_dir=ROOT,
    command="python /gen/run.py",
    work_dir="/ws",
    extra_binds=[(str(ROOT / "ws" / "skills"), "/skills")],
)
for a in argv:
    print(" ", a)

# %% [markdown]
# 逐段解读:
#
# | 参数段 | 作用 |
# |--------|------|
# | `--die-with-parent` | 父进程死则监禁死,不留孤儿 |
# | `--new-session` | 脱离控制终端(防 TTY 信号注入) |
# | `--unshare-pid/ipc/uts` | 隔离 PID/IPC/主机名命名空间 |
# | `--bind {root} /` | **核心**:root_dir 绑成监禁内的 `/`(09 本"虚拟 /"的真身) |
# | `--ro-bind /usr /usr` 等 | 只读借用宿主工具链(存在的才绑) |
# | `--ro-bind-try /etc/resolv.conf …` | 尽力提供 DNS/账号解析 |
# | `--dev /dev --proc /proc --tmpfs /tmp` | 最小设备/ proc / 干净 tmp |
# | `--chdir {work_dir}` | **cwd 对齐虚拟工作区** |
# | `-- /bin/sh -c {command}` | 命令保持 agent 视角,**不做改写**(监禁内 `/gen/...` 就是真的) |
#
# 注意与 09 本的根本区别:**有监禁时命令串不需要翻译**——监禁内的 `/` 就是 root_dir,
# 模型视角与实际路径天然一致;翻译层(及其"可信度规则")只在无监禁时需要。
#
# ## 3. jail 内 cwd 对齐与 skills 挂载

# %%
jail = BubbledLocalShellBackend(
    root_dir=ROOT,
    bwrap_path="/usr/bin/bwrap",   # 只在 execute 时才真正用到
    workspace_dir=ROOT / "ws",
    virtual_mode=True,
    system_files_path="",
)
print("jail 内 cwd:", jail._virtual_workspace_cwd())
print("额外挂载:", jail._skill_extra_binds(), "(空 = 临时工作区里还没有 skills/ 目录,挂载按需发生)")

# %% [markdown]
# - `_virtual_workspace_cwd`:计算工作区**在监禁内**的路径——`{root}/ws` 在监禁里就是 `/ws`,
#   所以 `pwd` 打印 `/ws`,与 agent 视角一致(工作区不在 root 下时回退 `/`);
# - `_skill_extra_binds`:工作区 ≠ root 时,把 `skills/`、`_builtin_skills/`(优先
#   `{system_files_path}/skills`)额外 bind 进监禁——**只有 execute 被监禁**,
#   文件工具仍走 deepagents virtual_mode 拼接(类 docstring `bwrap_shell.py:134-140`)。
#
# ## 4. 优雅降级:bwrap 不可用时
#
# 监禁启动失败(`FileNotFoundError`)会**清掉 bwrap 路径并退回翻译式宿主执行**
# (`bwrap_shell.py:232-238`),行为与 09 本一致——沙箱是"尽力而为",不是硬依赖:

# %%
show("src/octop_harness/backends/bwrap_shell.py", 228, 240)

# %% [markdown]
# 超时则 exit_code=124(沙箱里杀掉整组进程,不只是 shell)。
#
# ## 5. 真跑验证(Linux 读者专属)
#
# 在 Linux + bwrap 机器上,以下脚本应全部通过(取自 `tests/test_bwrap_shell_linux.py` 的场景):
#
# | 测试 | 验证什么 |
# |------|----------|
# | `test_host_file_visible_via_virtual_path` | root 下文件在监禁内以 `/a/x.txt` 可见 |
# | `test_execute_write_lands_under_root` | 监禁内写 `/x` 落在宿主 `{root}/x` |
# | `test_execute_starts_in_scoped_workspace` | cwd 是虚拟工作区路径(`pwd` = `/.octop/workspaces/…`) |
# | `test_factory_uses_bwrap_and_executes_scoped_script` | 工厂真的选中 Bubbled 并跑通脚本 |
# | `test_outside_root_not_visible` | root 之外的宿主文件**不可见**(隔离性) |
#
# macOS 读者看 `tests/test_bwrap_shell.py`(跨平台部分):门控矩阵、argv 形状、
# 虚拟 cwd、降级路径的表驱动测试。
#
# ## 6. 思考题
#
# 1. 为什么只监禁 `execute` 而不监禁文件工具?(提示:文件工具走 deepagents 协议,天然在 root 下;监禁的代价是什么)
# 2. `--unshare-pid` 之后监禁内的 `ps` 看到什么?这对模型诊断命令的输出有什么影响?
# 3. 降级路径(退回翻译式执行)是安全弱化——宿主该如何显式拒绝降级而不是默默接受?
# 4. `--ro-bind /usr /usr` 借用宿主工具链:如果宿主 `/usr/bin` 里有恶意二进制呢?(威胁模型:防谁?)
#
# ## 7. 延伸阅读
#
# - `tests/test_bwrap_shell.py` / `tests/test_bwrap_shell_linux.py`
# - `backends/local_shell.py`(09 本)——Bubbled 继承了它的翻译逻辑做降级
# - 下一本:[11_docker_and_remote.ipynb](11_docker_and_remote.ipynb)
