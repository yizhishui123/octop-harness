# %% [markdown]
# # 04 · 中间件链:顺序即策略
#
# **学习目标**
#
# - 记住 21 层中间件的**顺序**与每一层存在的理由——这是本库最核心的运行时设计;
# - 学会写自定义中间件(`wrap_model_call` / `awrap_tool_call` 钩子)并观察它在链中的位置;
# - 掌握 `runtime_config()` 这个易踩的读取姿势;
# - 现场做两个"顺序敏感"实验:PII 脱敏、媒体卸载。
#
# 源码:`src/octop_harness/middleware/` + `agent.py:1422-1564`(`_build_middleware`)。

# %%
# —— 标准前置(每本 notebook 自带,便于独立阅读)——
import base64
import os
import shutil
import sys
from pathlib import Path
from typing import Any

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

from octop_harness import HarnessAgent, HarnessAgentConfig, init_workspace

from learning.support.fake_model import FakeChatModelFactory, FAKE_MODEL_REF, fake_providers

import logging
logging.getLogger("deepagents.middleware.skills").setLevel(logging.ERROR)  # 空技能目录告警,无害

print("ok, 仓库根:", REPO)

# %% [markdown]
# ## 1. 全链顺序表(装配序)
#
# | # | 中间件 | 条件 | 职责 / 排序理由 |
# |---|--------|------|-----------------|
# | 0 | BootstrapMiddleware | 有引导任务且未完成 | **插到 0 号位**;系统提示追加 BOOTSTRAP.md |
# | 1 | TodoListMiddleware | `todos_enabled` | langchain 内置待办工具 |
# | 2 | ModelRouterMiddleware | 恒有 | 每轮换模型(05 本主角) |
# | 3 | ModelSettingsMiddleware | 恒有 | 合并 temperature/top_p/max_tokens |
# | 4 | SessionHeaderMiddleware | 恒有 | 维持会话头日志上下文 |
# | 5 | SkillFilterMiddleware | 恒有 | 技能热开关 + `/skill` 提示 |
# | 6 | ToolGuardMiddleware | `tool_guard_mode` | 危险命令拦截(block/warn/审批) |
# | 7 | FilesystemGuardMiddleware | 恒有 | 文件系统 deny 规则、路径改写 |
# | 8 | MCPToolMiddleware | 配了 MCP | MCP 工具按请求 opt-in 显形 |
# | 9 | ModelRetryMiddleware | `model_retry_enabled` | 指数退避重试 |
# | 10 | PIIMiddleware | `pii_enabled` | **先于媒体卸载**:它要看明文 |
# | 11 | MediaOffloadMiddleware | 恒有 | 大媒体块落盘换占位符;**先于记忆**:日志存占位符 |
# | 12 | CheckpointTsMiddleware | 恒有 | 给新消息盖时间戳 |
# | 13 | MemoryMiddleware | `memory_enabled` | 记忆召回/抽取 |
# | 14 | **用户中间件** | `cfg.middleware` | 你的自定义层插在这里 |
# | 15 | PeerAgentMiddleware | team 开启 | 同事 roster 挂**提示后缀**(前缀保缓存) |
# | 16 | ConversationModeMiddleware | 恒有 | Ask(只读)/Plan(只写 plans/)/Craft |
# | 17 | ToolsFilterMiddleware | 恒有 | 按 `tools_disabled` 裁剪工具表 |
# | 18 | ToolSearchMiddleware | 渐进加载开启 | 在**所有过滤之后**搜索最终可见工具集 |
# | 19 | TaskToolLastMiddleware | `task_tool_last` | task 工具排后(供应商前缀缓存) |
# | 20 | ContextUsageMiddleware | 恒有 | **最后**:快照匹配最终请求 |
#
# 顺序契约写在 `_build_middleware` 的 docstring 里:

# %%
show("src/octop_harness/agent.py", 1422, 1440)

# %% [markdown]
# ## 2. 钩子模型(langchain AgentMiddleware API)
#
# 本仓库的中间件都继承 `langchain.agents.middleware.AgentMiddleware`,常用四个钩子:
#
# | 钩子 | 时机 | 典型用途 |
# |------|------|----------|
# | `before_model(state, runtime)` | 模型调用前改状态 | 媒体卸载、记忆召回 |
# | `wrap_model_call(request, handler)` | 包住模型调用(可改 request) | 换模型、改参数、脱敏 |
# | `after_model(response, runtime)` | 模型返回后 | 记忆抽取、消息盖章 |
# | `wrap_tool_call(request, handler)` | 包住工具调用 | 拦截/审计/审批 |
#
# ## 3. 实验:写一个"侦察中间件"
#
# 把它塞进 `cfg.middleware`(第 14 号位),记录每一轮:模型是谁、几条消息、调了什么工具。

# %%
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

class SpyMiddleware(AgentMiddleware[Any, Any]):
    """记录模型调用与工具调用的侦察中间件。

    注意:wrap_model_call 必须同步/异步**成对定义**——langchain 不会自动把同步
    版本桥接到异步路径(本仓库自带的中间件也都是成对的)。只写同步版,异步
    调用会抛 NotImplementedError,再被 ModelRetryMiddleware 吞成错误消息。
    """

    def __init__(self) -> None:
        super().__init__()
        self.model_calls: list[dict[str, Any]] = []
        self.tool_calls: list[str] = []

    def _record(self, request: ModelRequest) -> None:
        from octop_harness.middleware.runtime import runtime_config
        configurable = runtime_config(request).get("configurable", {})
        self.model_calls.append({
            "model_type": type(request.model).__name__,
            "n_messages": len(request.messages or []),
            "configurable_model": configurable.get("model"),
            "n_tools": len(request.tools or []),
        })

    def wrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
        self._record(request)
        return handler(request)

    async def awrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
        self._record(request)
        return await handler(request)

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        self.tool_calls.append(str(request.tool_call.get("name")))
        return await handler(request)

# %%
WS = WORKSPACES / "nb04"
if WS.exists():
    shutil.rmtree(WS)
init_workspace(WS, language="zh")

spy = SpyMiddleware()
cfg = HarnessAgentConfig(
    workspace_dir=WS,
    providers=fake_providers(),
    default_model=FAKE_MODEL_REF,
    memory_enabled=False,
    web_search_tools=False,
    middleware=[spy],
)
factory = FakeChatModelFactory([
    AIMessage(content="", tool_calls=[{"name": "current_time", "args": {}, "id": "c1"}]),
    "工具轮次完成。",
])
agent = HarnessAgent(cfg, model_factory=factory)

res = await agent.call("先看时间再回答")
print("工具调用被侦察到:", spy.tool_calls)
print("模型调用记录:")
for c in spy.model_calls:
    print("  ", c)

# %% [markdown]
# 两条模型调用记录(ReAct 两轮),工具 `current_time` 被 `awrap_tool_call` 捕获——
# 你的中间件确实插在生产链路里,与 PII、媒体卸载们同台。
#
# ## 4. `runtime_config()`:读配置的正确姿势
#
# 中间件里想读 `RunnableConfig`(thread_id、configurable……),直觉会写
# `request.runtime.config`——**但** `ModelRequest.runtime` 是带 `context` 的 `Runtime` 对象,
# 不一定有 `.config`。本仓库提供了 `runtime_config()`(`middleware/runtime.py`)统一处理各版本差异:

# %%
show("src/octop_harness/middleware/runtime.py", 1, 30)

# %% [markdown]
# 它内部优先 `langgraph.config.get_config()`。刚才会 spy 里已经用了它(`configurable_model`)。
#
# ## 5. 顺序敏感实验一:PII 脱敏
#
# 默认 `pii_enabled=True`,检测:OpenAI(`sk-…`/`sk-proj-…`)与 Anthropic(`sk-ant-…`)密钥形态、
# 大陆手机号、大陆居民身份证(含 GB/T 2260 省份码 + MOD 11-2 校验位,`middleware/pii.py`)。
# 让假模型"说漏嘴",看输出面被如何处理:

# %%
from octop_harness.middleware.pii import detect_pii

LEAK = "我的密钥是 sk-proj-abc123DEF456ghi789JKL,手机号 13800138000。"
for match in detect_pii(LEAK):   # 返回 dict:{"type", "value", "start", "end"}
    print(f"检测到 {match['type']:20s} → {match['value']!r}")

# %%
# 身份证的校验位是现场算出来的——MOD 11-2,自己验一遍(这正是 _valid_resident_id 做的事)
def resident_id_check_digit(first17: str) -> str:
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    mapping = "10X98765432"
    total = sum(int(d) * w for d, w in zip(first17, weights))
    return mapping[total % 11]

demo_id = "11010519491231002" + resident_id_check_digit("11010519491231002")
print("构造的合法身份证(仅算法演示):", demo_id)
print("detect_pii 认出:", [m["type"] for m in detect_pii(f"证件 {demo_id} 勿存")])
bad_id = demo_id[:-1] + ("0" if demo_id[-1] != "0" else "1")
print("改掉校验位后:", [m["type"] for m in detect_pii(f"证件 {bad_id}")], "(空 = 校验不过,不算 PII)")

# %%
# 放进模型输出面,看 PIIMiddleware 的实际处理(默认策略 mask)
factory_pii = FakeChatModelFactory([f"好的,记录:{LEAK} 证件 {demo_id}。"])
cfg_pii = HarnessAgentConfig(
    workspace_dir=WS, providers=fake_providers(), default_model=FAKE_MODEL_REF,
    memory_enabled=False, web_search_tools=False,
)
agent_pii = HarnessAgent(cfg_pii, model_factory=factory_pii)
res_pii = await agent_pii.call("请复述这些信息")
print("模型原始输出被处理为:")
print(" ", res_pii["messages"][-1].content)
await agent_pii.aclose()

# %% [markdown]
# ## 6. 顺序敏感实验二:媒体卸载
#
# 多模态消息里内联 base64 超 4 KiB(`media_offload_min_bytes`)时,
# `MediaOffloadMiddleware` 在**第一次轮次之后**把它落盘到 `.media-cache/`,消息里换成轻量占位符——
# 于是 PII(在它前面)仍能看到明文,而记忆/会话日志(在它后面)只存占位符。
# **这就是"PII → 媒体卸载 → 记忆"这条排序的全部理由。**

# %%
from octop_harness.request import ChatRequest

fake_png = base64.b64encode(b"\x89PNG-fake-bytes" + os.urandom(6000)).decode()  # > 4 KiB
factory_media = FakeChatModelFactory(["", "第二轮:我已经不需要那张图了。"])
cfg_media = HarnessAgentConfig(
    workspace_dir=WS, providers=fake_providers(), default_model=FAKE_MODEL_REF,
    memory_enabled=False, web_search_tools=False,
)
agent_media = HarnessAgent(cfg_media, model_factory=factory_media)

t = "m1"
img_block = {"type": "image", "base64": fake_png, "mime_type": "image/png"}
await agent_media.call(ChatRequest(messages=[{"role": "user", "content": [
    {"type": "text", "text": "看看这张图"}, img_block,
]}], thread_id=t))
await agent_media.call(ChatRequest(messages="第二轮,直接回答", thread_id=t))

cache = WS / ".media-cache"
print(".media-cache 存在:", cache.exists())
for p in sorted(cache.glob("*")) if cache.exists() else []:
    print("  ", p.name, f"{p.stat().st_size} bytes")

hist = await agent_media.aget_history(t)
first_human_content = hist[0].content
if isinstance(first_human_content, list):
    kinds = [b.get("type") for b in first_human_content]
    print("第一轮 human 消息的块类型(卸载后):", kinds)

await agent_media.aclose()

# %% [markdown]
# 原来的 `image` 块在历史里变成了轻量占位符文本块;原始字节躺在 `.media-cache/`。
# 想深挖可读 `middleware/media_offload.py` 的模块 docstring——它对
# `{type: image, base64, mime_type}`(v1 标准)与 `image_url`(OpenAI 形态)都认。
#
# ## 7. 更多排序理由速查(源码注释原文)
#
# `_build_middleware` 里每处插入都带注释,值得精读:

# %%
show("src/octop_harness/agent.py", 1489, 1500)    # PII → 媒体卸载 → 记忆
print("……")
show("src/octop_harness/agent.py", 1517, 1522)    # 用户中间件 / Peer 后缀保缓存
print("……")
show("src/octop_harness/agent.py", 1566, 1584)    # ToolSearch 在所有过滤之后

# %% [markdown]
# ## 8. 思考题
#
# 1. 若把 PIIMiddleware 挪到 MediaOffloadMiddleware **之后**,密钥还拦得住吗?(提示:占位符里没有明文,但落盘文件里有)
# 2. 你的自定义中间件在 14 号位:能看见 PeerAgentMiddleware 挂的工具吗?能看见被 ToolsFilter 裁掉的工具吗?
# 3. ContextUsageMiddleware 为什么必须最后?如果它排在 ToolsFilter 之前,用量统计会偏差什么?
# 4. `awrap_tool_call` 里调用 `handler(request)` 前后分别能做什么?若想给所有工具加耗时日志,改 spy 的哪里?
#
# ## 9. 延伸阅读
#
# - `middleware/` 目录浏览一遍:每份文件的 docstring 都是一课
# - `tests/test_skill_filter.py`、`tests/test_tool_guard_middleware.py`、`tests/test_filesystem_guard.py`
# - 下一本:[05_model_routing_and_context.ipynb](05_model_routing_and_context.ipynb) —— 2 号位与 20 号位的深潜
