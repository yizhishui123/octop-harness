# %% [markdown]
# # 01 · 配置体系与核心理念
#
# **学习目标**
#
# - 吃透配置三件套 `HarnessAgentConfig` / `ProviderConfig` / `ModelConfig` 的结构与关系;
# - 理解 frozen dataclass 的序列化契约(`to_dict` / `from_dict` / `_unserializable_fields`);
# - 掌握 provider 的三个来源:显式配置、环境变量探测、JSON 预设;
# - 体会三大默认值哲学:零依赖优先、fail-soft 只给体验、用户编辑神圣。
#
# **为什么先学配置**:配置对象是整个组装线的"图纸"。`HarnessAgent.__init__` 的每一步都在读它;
# 把它的字段分组记住,后面读 `agent.py` 会快一倍。
#
# 源码位置:`src/octop_harness/config/__init__.py`(约 1300 行)+ `config/env.py`。

# %%
# —— 标准前置(每本 notebook 自带,便于独立阅读)——
import sys
from pathlib import Path

HERE = Path.cwd()
REPO = HERE.parent if HERE.name == "learning" else HERE
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

WORKSPACES = REPO / "learning" / ".workspaces"

def show(path: str, start: int, end: int) -> None:
    """带行号打印仓库内源码片段,如 show("src/octop_harness/agent.py", 145, 202)"""
    lines = (REPO / path).read_text(encoding="utf-8").splitlines()
    for i in range(start - 1, min(end, len(lines))):
        print(f"{i + 1:5d} │ {lines[i]}")

from octop_harness import HarnessAgentConfig, ModelConfig, ProviderConfig

print("ok, 仓库根:", REPO)

# %% [markdown]
# ## 1. 三件套的关系
#
# ```text
# HarnessAgentConfig(~90 字段,frozen)
#   ├── providers: list[ProviderConfig]      ← 每个提供商一个(base_url/api_key/models)
#   │      └── models: list[ModelConfig]     ← 每个模型一条(能力/token 上限/模态)
#   ├── default_model / multimodal_model     ← 引用 "provider_id/model_id"
#   ├── backend / workspace_dir / system_files_path …
#   └── 五花八门的功能开关(pii_* / memory_* / tool_guard_* / team_* …)
# ```
#
# 注意 `providers` 是 **list 而非 dict**(以 `ProviderConfig.id` 为键),序列化为 JSON 数组。

# %%
# HarnessAgentConfig 有多少字段?默认值长什么样?
import dataclasses

cfg = HarnessAgentConfig()  # workspace_dir 默认 cwd;构造本身不做任何 I/O
fields = dataclasses.fields(cfg)
print(f"共 {len(fields)} 个字段。挑几个有故事的:\n")
INTERESTING = [
    "workspace_dir", "system_files_path", "language", "protocol",
    "default_model", "todos_enabled", "task_tool_last",
    "pii_enabled", "tool_guard_mode", "ask_user_enabled",
    "memory_enabled", "memory_backend", "memory_extract_trigger_mode",
    "team_enabled", "peer_invoke_mode", "web_search_tools",
    "media_offload_enabled", "media_offload_min_bytes",
    "tool_search_mode", "model_retry_enabled", "bootstrap_enabled",
]
for name in INTERESTING:
    val = getattr(cfg, name, "<无此字段>")
    print(f"  {name:32s} = {val!r}")

# %% [markdown]
# ## 2. frozen:配置对象不可变
#
# `HarnessAgentConfig` 是 **frozen dataclass**——实例化后不能改字段。这带来两个后果:
#
# 1. 配置可以被安全地共享、缓存、比较;
# 2. "改配置"只能通过 `dataclasses.replace()` 生成新对象(热更新时就是这么做的)。

# %%
import dataclasses

try:
    cfg.language = "en"  # type: ignore[misc]
except dataclasses.FrozenInstanceError as e:
    print("修改被拒绝 →", type(e).__name__)

cfg2 = dataclasses.replace(cfg, language="en")
print("replace 生成新对象:", cfg2.language, "| 原对象不变:", cfg.language)

# %% [markdown]
# ## 3. ModelConfig:token 上限的互相回填
#
# `max_input_tokens` 与 `context_window` 两个历史字段会在 `__post_init__` 里互相补齐——
# 这是典型的"新旧配置兼容"处理。

# %%
show("src/octop_harness/config/__init__.py", 365, 372)

# %%
m1 = ModelConfig(id="legacy", max_input_tokens=8000)   # 只给 max_input_tokens
m2 = ModelConfig(id="modern", context_window=128_000)  # 只给 context_window
print(f"legacy: max_input_tokens={m1.max_input_tokens}, context_window={m1.context_window}")
print(f"modern: max_input_tokens={m2.max_input_tokens}, context_window={m2.context_window}")
print(f"多模态判定 is_multimodal: text-only={m1.is_multimodal}", end=" ")
m3 = ModelConfig(id="vision", input=["text", "image"])
print(f" vision={m3.is_multimodal}")

# %% [markdown]
# ## 4. ProviderConfig:`id` 是必填的第一 positional 参数
#
# 这是本仓库的一个易踩坑(AGENTS.md §8 专门列了):`id` 用来组成模型引用 `"{provider_id}/{model_id}"`,
# 必须显式给。`protocol` 支持 `openai` / `anthropic` / `bedrock`,默认按 openai 兼容处理。

# %%
try:
    ProviderConfig(base_url="https://api.example.com/v1", api_key="sk-xxx")  # type: ignore[call-arg]
except TypeError as e:
    print("缺 id →", e)

p = ProviderConfig(
    id="my-provider",
    base_url="https://api.example.com/v1",
    api_key="sk-xxx",  # 学习用占位符,不是真实密钥
    models=[ModelConfig(id="k1", context_window=64_000)],
)
print("ok:", p.id, "| 模型:", [m.id for m in p.models], "| protocol:", p.protocol)

# %% [markdown]
# ## 5. 序列化契约:to_dict / from_dict / _unserializable_fields
#
# - `to_dict()` 输出 JSON 友好字典;`from_dict()` **忽略未知键**(向前兼容);
# - 带着活的 Python 对象的字段(`model_selector`、`tools`、`middleware`、`checkpointer`、
#   `permissions`、`interrupt_on`、`response_format`)进 `_unserializable_fields`,
#   **双向静默丢弃**——序列化再反序列化后这些字段必然回到默认值。这是刻意的契约,不是 bug。

# %%
show("src/octop_harness/config/__init__.py", 963, 975)

# %%
from typing import Any

def fake_tool(text: str) -> str:  # 一个"活对象"字段:函数无法 JSON 序列化
    return text

cfg_a = HarnessAgentConfig(
    workspace_dir=WORKSPACES,
    providers=[p],
    default_model="my-provider/k1",
    tools=[fake_tool],
)
d = cfg_a.to_dict()
print("to_dict 后还有 'tools' 键吗?", "tools" in d)

cfg_b = HarnessAgentConfig.from_dict(d)
print("from_dict 回来 tools =", cfg_b.tools, "(回到默认)")
print("providers 往返一致?", ProviderConfig.from_dict(d["providers"][0]) == cfg_a.providers[0])
print("default_model 往返一致?", cfg_b.default_model == cfg_a.default_model)

# %% [markdown]
# > 文档化权衡:`ProviderConfig.to_dict()` 会**明文**带上 `api_key`(`config/__init__.py:506` 附近有注释)。
# > 这是给宿主做"配置同步"用的;也因此仓库规定任何示例/测试里只准出现 `"sk-xxx"` 占位符。
#
# ## 6. Provider 的三个来源
#
# 1. **显式配置**:`cfg.providers`(上面演示过);
# 2. **环境变量探测**:`detect_providers_from_env()`(`config/env.py:133`);
# 3. **JSON 预设**:`providers/provider_template.json`(单一事实来源,CLI 向导读它)。
#
# 优先级在 `agent.py` 的 `_init_model_factory()`(`agent.py:1197`):注入工厂 → `cfg.providers` → 环境探测,全空才报错。

# %%
# 环境变量探测:不需要真实 Key,摆几个变量就能看到探测逻辑(用完即删)
import os

os.environ["HARNESS_PROVIDER_FAKELIVE_API_KEY"] = "sk-xxx"
os.environ["HARNESS_PROVIDER_FAKELIVE_BASE_URL"] = "https://fakelive.example.com/v1"

from octop_harness.config.env import detect_providers_from_env

providers, default_model = detect_providers_from_env()
for prov in providers:
    print(f"探测到 provider: {prov.id} | base_url={prov.base_url} | models={[m.id for m in prov.models]}")
print("默认模型:", default_model)

del os.environ["HARNESS_PROVIDER_FAKELIVE_API_KEY"], os.environ["HARNESS_PROVIDER_FAKELIVE_BASE_URL"]

# %% [markdown]
# 探测顺序(`config/env.py` 模块 docstring):① `HARNESS_PROVIDER_<NAME>_API_KEY`(可配 `_BASE_URL`/`_PROTOCOL`)
# → ② `OPENAI_API_KEY` 兜底 → ③ 预设 JSON 里声明了 `api_key_env` 且已设置的预设。
# 默认模型依次取 `HARNESS_DEFAULT_MODEL` → `OPENAI_MODEL_NAME` → 唯一 provider 的第一个模型。
#
# > 注意:config 的 `from_env()`(`config/__init__.py:1113`)刻意**只建空 providers 配置**,
# > 真正的探测延迟到 agent 构造时——因为环境可能被宿主注入,晚探测更准。

# %%
# JSON 预设:provider_template.json 是唯一事实来源(不要在 Python 里硬编码 provider!)
import json

presets = json.loads((REPO / "src/octop_harness/providers/provider_template.json").read_text(encoding="utf-8"))
names = list(presets.keys()) if isinstance(presets, dict) else [item.get("id") for item in presets]
print("预设条目:", names[:12], "..." if len(names) > 12 else "")

sample = presets["openai"] if isinstance(presets, dict) else next(i for i in presets if i.get("id") == "openai")
print("\nopenai 预设(截取):")
print(json.dumps({k: v for k, v in sample.items() if k in ("id", "name", "base_url", "api_key_env")}, ensure_ascii=False, indent=2))
print("模型目录前 5 个:", [m.get("id") for m in sample.get("models", [])][:5])

# %% [markdown]
# ## 7. workspace_dir 的校验:绝对路径或 rootfs 路径
#
# `workspace_dir` 可以是宿主机绝对路径,也可以是 **agent 视角的 rootfs 路径**(`/.octop/workspaces/<id>`,
# 由 harness 映射到 `{root_dir}/…`)。相对路径直接拒绝——本系列 00 的冒烟测试就撞过这堵墙。

# %%
show("src/octop_harness/config/__init__.py", 855, 862)

# %%
for candidate in ("relative/ws", "/.octop/workspaces/abc", "/tmp/absolute/ws"):
    try:
        HarnessAgentConfig(workspace_dir=candidate)
        status = "✓ 允许"
    except ValueError as e:
        status = f"✗ 拒绝({e})"
    print(f"{candidate!r:35s} {status}")

# %% [markdown]
# Windows 兼容的细节:`/.octop/...` 这种 rootfs 路径没有盘符,所以它**不**按 Windows 绝对路径规则解析
# (`_is_rootfs_path`,`config/__init__.py:1213` 附近)——同一份配置在 Windows 上也成立。
#
# ## 8. 三大默认值哲学(背下来)
#
# | 哲学 | 含义 | 源码落点 |
# |------|------|----------|
# | **零依赖优先** | 核心安装不带可选依赖;重型依赖走 `[extras]`(desktop/web-search-all/…) | `pyproject.toml` |
# | **体验 fail-soft,检查严格** | 启动/调用时的缺东西→清晰的警告与指引;mypy/lint/test 永不让步 | 全仓库 |
# | **用户编辑神圣** | `init()` 默认不覆盖已有文件;`overwrite=True` 才刷新;技能只在版本戳变化时擦除重放 | `init.py`(第 12 本详解) |
#
# ## 9. 思考题
#
# 1. 为什么 `providers` 设计成 list 而不是 `{id: ProviderConfig}` 字典?(提示:序列化形态、JSON 互转、增删顺序)
# 2. `_unserializable_fields` 双向静默丢弃,什么场景下会咬人?(提示:宿主把 to_dict 存档再恢复)
# 3. `api_key` 明文进 `to_dict()` 是权衡的结果——如果由你设计,怎么在"配置同步方便"与"不落盘密钥"之间取舍?
# 4. `ModelConfig` 的 `__post_init__` 回填发生在**构造时**而非使用时,为什么这样更安全?
#
# ## 10. 延伸阅读
#
# - `tests/config/` —— 配置序列化的完整测试(往返、未知键、旧格式兼容)
# - `examples/01_quickstart.py`(需 Key)—— 环境探测的真实用法
# - `examples/02_custom_provider.py`(需 Key)—— 自定义 OpenAI 兼容端点 + 双模型路由
# - 下一本:[02_agent_assembly.ipynb](02_agent_assembly.ipynb) —— HarnessAgent 组装流水线
