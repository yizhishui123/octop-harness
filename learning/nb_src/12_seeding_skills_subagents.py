# %% [markdown]
# # 12 · 工作区种子、技能目录与子代理
#
# **学习目标**
#
# - 吃透 `init_workspace` 的种子流水线:模板 md → 内置技能(版本戳)→ 内置子代理;
# - 理解**文件级 en→zh 回退**与 `InitResult` 的可观测性;
# - 玩转技能目录三级根(`_builtin_skills` → `skills/` → 额外目录,后者同名覆盖);
# - 看懂子代理的 YAML frontmatter 加载与**编译期剥离**(为什么子代理没有 MCP/ask_user)。
#
# 源码:`init.py`、`builtin/_sync.py`、`builtin/templates.py`、`skills/catalog.py`、`subagents/loader.py`。

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

from octop_harness import HarnessAgent, HarnessAgentConfig, init_workspace

from learning.support.fake_model import FakeChatModelFactory, FAKE_MODEL_REF, fake_providers

import logging
logging.getLogger("deepagents.middleware.skills").setLevel(logging.ERROR)

print("ok, 仓库根:", REPO)

# %% [markdown]
# ## 1. 种子流水线
#
# `init_workspace`(`init.py:142`,无配置引导版)与 `HarnessAgent.init_workspace()`(经
# BackendWorkspace 的完整版)最终都汇入 `_seed_workspace`(`init.py:87`):
#
# ```text
# ① md 模板(builtin/md_files/{en,zh}/):AGENTS / BOOTSTRAP / MEMORY / PROACTIVE / USER
#    · 已存在 → 跳过(用户编辑神圣);overwrite=True → 强制刷新
#    · BOOTSTRAP.md 里的 {{BOOTSTRAP_MARKER}} 被替换成解析后的 .bootstrapped 路径
# ② 内置技能(builtin/skills/{en,zh}/<slug>/SKILL.md)→ _builtin_skills/
#    · _builtin_skills/.version 记录包版本;版本一致 → 跳过重拷(升级才刷新)
# ③ 内置子代理(builtin/agents/{en,zh}/general-purpose.md)→ agents/
# ```

# %%
WS = WORKSPACES / "nb12"
if WS.exists():
    shutil.rmtree(WS)

result = init_workspace(WS, language="zh")
print("模板:", [Path(p).name for p in result.templates_created])
print("技能同步:", result.skills_synced, "| 技能回退(en 顶替 zh 缺失):", [Path(p).name for p in result.skills_fallback][:5])
print("agent:", [Path(p).name for p in result.agents_created])
print("版本戳内容:", (WS / "_builtin_skills" / ".version").read_text().strip())

builtin_skills = sorted(p.name for p in (WS / "_builtin_skills").iterdir() if p.is_dir())
print(f"\n内置技能 {len(builtin_skills)} 个:", ", ".join(builtin_skills))

# %% [markdown]
# **版本戳机制**:`.version` 存的是包版本(`importlib.metadata` 解析 `[project].version`)。
# 库升级 → 戳不匹配 → 整体擦除重放;版本一致 → 一秒跳过。
# `overwrite=True` 且同步失败时,先清戳再重试一次(`init.py:126-128`)。
#
# **文件级 i18n 回退**:非 en 语言先拷整棵 en 树,再用 zh 树**逐文件覆盖**——
# zh 只翻译了 SKILL.md 也没关系,templates/references/scripts 继承 en 的。
# 上面的 `skills_fallback` 就是"zh 缺、用 en 顶"的记录。
#
# ## 2. BOOTSTRAP:新人引导的一整个闭环

# %%
bootstrap = (WS / "BOOTSTRAP.md").read_text()
print(bootstrap[:400])
print("……")
print("\n含 {{BOOTSTRAP_MARKER}} 占位?", "{{BOOTSTRAP_MARKER}}" in (REPO / "src/octop_harness/builtin/md_files/zh/BOOTSTRAP.md").read_text())

# %% [markdown]
# 闭环(02 本提过,这里串起来):`BootstrapMiddleware`(0 号位)把 BOOTSTRAP.md 追加进系统提示
# (**请求级**,不进 checkpoint),直到工作区出现 `.bootstrapped` 标记;模型用 write 工具写下标记
# 或写 USER.md → `_on_bootstrap_complete` → 触发宿主钩子或本地重编译图(此时 USER.md/SOUL.md
# 的记忆才被加载)。注意:**默认没有 SOUL.md 模板**——SOUL.md 属于宿主人设,由
# `multi_agent_demo/*/SOUL.md` 这类语料提供。
#
# ## 3. 技能目录:三级根与同名覆盖
#
# `list_skill_summaries`(`skills/catalog.py:177`,async)按三级根扫描:
# `_builtin_skills`(kind=builtin)→ 工作区 `skills/`(kind=workspace)→ 额外 `skills_dir`;
# **后面的根同名覆盖前面的**——工作区技能可以"盖掉"内置技能。

# %%
from octop_harness.backends.workspace import BackendWorkspace
from octop_harness.skills.catalog import list_skill_summaries

ws_facade = BackendWorkspace(
    fake_providers_backend := __import__("octop_harness.backends", fromlist=["resolve_backend"]).resolve_backend(
        {"type": "filesystem", "root_dir": WS.parent, "virtual_mode": False},
        workspace_dir=WS, system_files_path="",
    ),
    WS,
)

async def catalog_snapshot():
    return await list_skill_summaries(ws_facade)

summaries = await catalog_snapshot()
print(f"目录里 {len(summaries)} 个技能,前 6 个:")
for s in summaries[:6]:
    print(f"  {s.get('slug'):22s} kind={s.get('kind')}  {str(s.get('summary'))[:36]}")

# %%
# 实验:工作区技能覆盖内置技能(同名 slug)
custom = WS / "skills" / "plan"          # 与内置 plan 同名
custom.mkdir(parents=True, exist_ok=True)
(custom / "SKILL.md").write_text(
    "---\nname: plan\ndescription: 我方自定义的计划技能,覆盖内置版本\n---\n\n自定义内容。\n"
)
summaries2 = await catalog_snapshot()
plan = next(s for s in summaries2 if s.get("slug") == "plan")
print("覆盖后 plan 的 kind:", plan.get("kind"), "| summary:", plan.get("summary"))

# %% [markdown]
# 目录解析细节:YAML frontmatter 的 `name/description` 是给模型看的;
# `octop`/`harness` 等扩展字段是展示元数据(label/emoji/icon);`metadata.removed: true` 可以**隐藏**技能。
# `SkillFilterMiddleware`(04 本 5 号位)负责运行时开关与 `/skill <slug>` 提示注入。
#
# ## 4. 子代理:frontmatter 加载与编译期剥离

# %%
agent_md = (WS / "agents" / "general-purpose.md").read_text()
print(agent_md[:420], "…")

# %%
from octop_harness.subagents.loader import parse_agent_markdown

parsed = parse_agent_markdown(agent_md, path_fragment="agents/general-purpose.md")
print("解析键:", sorted(parsed.keys()))
print("name:", parsed.get("name"), "| description:", str(parsed.get("description"))[:60])

# %% [markdown]
# `parse_agent_markdown`(`subagents/loader.py:159`)产出 deepagents `SubAgent` dict:
# frontmatter 的 `tools:` 把名字映射回父工具池,`inherit`/缺省 → 继承全部。
# 然后 `_resolve_subagents`(`agent.py:1619-1661`)做**编译期剥离**:

# %%
show("src/octop_harness/agent.py", 1637, 1652)

# %% [markdown]
# 理由:子代理跑在**嵌套图**里,**不继承**父级的中间件链与 HITL——
# 带着 MCP 工具(每请求 opt-in 的门在父级中间件上)或 `ask_user_question`
# (中断审批在父级)会直接出事故,所以在编译时就不给。
#
# ## 5. 思考题
#
# 1. 为什么技能刷新用"版本戳整树擦除"而不是逐文件 diff?(提示:删除的技能也要消失)
# 2. 工作区同名覆盖内置技能——如果只是想**禁用**内置技能而非替换,有几种办法?(提示:`/skills`、cfg、removed 元数据)
# 3. 子代理不继承中间件:如果子代理也需要 PII 脱敏,现在怎么办?改成"子图继承中间件"要付出什么代价?
# 4. `init()` 默认不覆盖——但技能树却是"版本变了就整体擦除重放"。两者矛盾吗?各保护的是什么?
#
# ## 6. 延伸阅读
#
# - `tests/test_init.py`(幂等/覆盖/回退)、`tests/test_skill_filter.py`、`tests/test_subagents*.py`
# - `examples/03_with_skills.py`(需 Key)—— 自定义技能实战
# - 下一本:[13_memory_and_teams.ipynb](13_memory_and_teams.ipynb)
