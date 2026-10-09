# %% [markdown]
# # 11 · 沙箱三:Docker 与远程沙箱
#
# **学习目标**
#
# - 吃透 DockerSandbox 的**"同路径,两处存在"**设计(刻意不 bind-mount);
# - 记住资源限额默认值(network=none / 512MB / 1 CPU / 256 pids / sleep infinity);
# - 理解容器命名三档作用域(agent / user / fixed)与孤儿容器处理;
# - 看懂路径钳制(`_clamp_to_workspace`)与虚拟路径还原(`_to_virtual_path`);
# - 认识 OpenSandbox(远程沙箱)与两个 `[extra]` 的 fail-soft 报错。
#
# 本机没装 docker SDK/守护进程时自动降级为"源码 + 纯函数"学习(这就是本本的写法)。
# 源码:`backends/docker_sandbox.py`(约 1000 行)、`backends/opensandbox_sandbox.py`。

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

from octop_harness.backends import resolve_backend, spec_supports_execution

print("ok, 仓库根:", REPO)

# %% [markdown]
# ## 1. 依赖门:fail-soft 的标准姿势
#
# `docker` / `opensandbox` 都是可选 extra。没装时,工厂给出**指名道姓**的报错
# (而不是半路冒出一个 `ModuleNotFoundError: No module named 'docker'`):

# %%
for spec in ({"type": "docker"}, {"type": "opensandbox"}):
    try:
        resolve_backend(spec, workspace_dir=Path(tempfile.mkdtemp()), system_files_path="")
    except ImportError as e:
        print(f"{spec['type']:12s} → ImportError:{e}")

print("\n不需要实例化就能判断执行能力:")
print("  docker      →", spec_supports_execution({"type": "docker"}))
print("  opensandbox →", spec_supports_execution({"type": "opensandbox"}))

# %% [markdown]
# ## 2. 核心设计:"同路径,两处存在"(Same path, two places)
#
# 模块 docstring(`docker_sandbox.py:1-31`)是本仓库写得最好的设计文档之一:

# %%
show("src/octop_harness/backends/docker_sandbox.py", 1, 31)

# %% [markdown]
# 画成图:
#
# ```text
# 宿主机                                 容器(sandbox_fs=True, virtual_mode=True)
# {workspace_dir}/                       /workspace(同一条绝对路径字符串!)
#   ├─ sessions/*.jsonl                  ├─ (agent 写的文件)
#   ├─ memory.sqlite                     └─ (put_archive/get_archive 进出)
#   └─ checkpoints.sqlite
#   ← 宿主进程直接读写(真实 fd)          ← 所有 I/O 经 Docker SDK exec_run
#
# 刻意不 bind-mount:两侧独立,互不踩脚;同路径只是让"agent 视角"无需翻译。
# ```
#
# ## 3. 资源限额默认值(安全基线)

# %%
show("src/octop_harness/backends/docker_sandbox.py", 454, 480)

# %% [markdown]
# 默认:**`network_mode="none"`(断网!)、512MB 内存、1.0 CPU、256 pids、`sleep infinity` 常驻**。
# `allow_network=True` 才放开网络——安全默认值哲学的又一例。
#
# ## 4. 命名三档:agent / user / fixed
#
# `resolve_sandbox_name`(`docker_sandbox.py:204`)是纯函数,离线可玩:

# %%
from octop_harness.backends.docker_sandbox import resolve_sandbox_name

print("agent 档:", resolve_sandbox_name(sandbox_scope="agent", agent_id="abc123"))
print("user 档: ", resolve_sandbox_name(sandbox_scope="user", username="alice"))
print("fixed 档:", resolve_sandbox_name(sandbox_scope="fixed", sandbox_id="team-shared"))
print("显式名:  ", resolve_sandbox_name(container_name="my-sandbox"))
try:
    resolve_sandbox_name(sandbox_scope="fixed")
except ValueError as e:
    print("fixed 缺 id →", e)

# %% [markdown]
# | 档位 | 容器名 | 语义 |
# |------|--------|------|
# | `agent`(默认) | `{prefix}_agent_{agent_id}` | 每 agent 独占;重建 agent 复用同一容器 |
# | `user` | `{prefix}_{username}` | 同一用户的多专家共享(Windows 子树专家场景) |
# | `fixed` | `sandbox_id` | 完全显式,团队共享 |
#
# 命名容器在 `close()` 时只 detach 不删除(`destroy()` 才销毁);
# 启动失败的命名容器被改名为 `{name}.orphan.{ts}` 后重建——不留脏状态。
#
# ## 5. 路径钳制与虚拟还原
#
# 容器内路径与虚拟路径的双向换算(`docker_sandbox.py:657-700`):

# %%
show("src/octop_harness/backends/docker_sandbox.py", 657, 700)

# %% [markdown]
# - `_clamp_to_workspace`:一切容器路径钳到工作区根内(防逃逸到容器系统目录);
# - `_to_virtual_path`:ls/glob 的结果转回虚拟 `/…` 给模型;**外来容器路径**(`/bin` 等)
#   刻意**不**重定位——它们本来就在容器命名空间里,不该被硬塞进工作区;
# - 一个重要的坑:`als`/`aglob` 等 **async 方法被显式路由回映射过的 sync 方法**——
#   deepagents ≥0.6.12 的 `BaseSandbox` 异步默认实现会绕过覆写、直接列容器的真 `/`(793-828 行注释)。
#
# ## 6. 其他工程细节速览
#
# - **execute 超时**:工作线程 + `_kill_exec` 杀容器内 PID(不是杀宿主线程);
# - **env 隔离**:容器 env 只给最小 `PATH`/`HOME` 基底(`runtime_env.docker_base_env`),
#   **绝不**透传宿主全量 env;工作区 `.env` 有 2 秒 TTL 缓存,每次执行前刷新;
# - **镜像拉取**:凭据助手(macOS `docker-credential-osxkeychain` 缺失)报错时自动匿名重拉;
# - **send_file**:从容器 `get_archive` 下载后物化(经 06 本的 delivery 缓存)。
#
# ## 7. OpenSandbox:远程沙箱
#
# `opensandbox_sandbox.py`:官方 SDK(`opensandbox>=0.1.16`),构造即 `SandboxSync.create`,
# `close()` 走 destroy → kill → close 链。只实现三个原语:`execute` / `upload_files` /
# `download_files`;读错误时跑一个 shell 探针(`if [ -d … ]`)区分 DIR/MISSING/NOREAD。
# 对 harness 来说它只是另一个 `sandbox_fs=True` 的后端——**统一协议的胜利**。
#
# ## 8. `[可选·需 Docker]` 真跑清单
#
# 本机若有 docker,装上 extra 后可跑(`uv sync --group dev --extra docker`):
#
# ```python
# from octop_harness.backends import resolve_backend
# b = resolve_backend({"type": "docker", "workspace_dir": "...", "agent_id": "nb11"},
#                     workspace_dir="...", system_files_path="")
# b.write("/hello.txt", "in container")     # 落在容器工作区
# print(b.execute("cat /hello.txt").output) # 容器内执行
# print(b.ls("/"))                          # 返回虚拟路径
# ```
#
# 无 docker 时,`tests/test_docker_sandbox.py`(全部 mock SDK)是行为契约的权威清单:
# 生命周期、env 过滤、上传下载回环、路径映射(含 `als` 不可绕过)、容器复用/孤儿改名、
# 命名三档、超时杀进程、send_file 物化——每个场景一个测试。
#
# ## 9. 思考题
#
# 1. "同路径,两处存在"如果不刻意维持同路径,会付出什么代价?(提示:模型提示词里的路径世界观)
# 2. 为什么 async 方法必须显式路由回 sync?这暴露了继承式框架的什么风险?
# 3. `network_mode="none"` 默认断网——但 web_fetch 工具还在宿主侧可用。这个"内外分工"合理吗?
# 4. 三档命名作用域分别对应什么宿主形态?(提示:Octop 多专家、Windows 子树、团队共享)
#
# ## 10. 延伸阅读
#
# - `tests/test_docker_sandbox.py`、`tests/test_opensandbox.py`
# - `runtime_env.py` 的四种"生成环境"(host execute / docker / ACP 子进程 / MCP stdio)——15 本展开
# - 沙箱模块完;下一模块:[12_seeding_skills_subagents.ipynb](12_seeding_skills_subagents.ipynb)
