# %% [markdown]
# # 05 · 模型路由与上下文管理
#
# **学习目标**
# - 吃透**逐轮模型选择**的优先级链(显式覆盖 > 用户选择器 > 多模态自动切换 > 默认模型);
# - 理解 `ChatModelFactory` 的缓存语义与 `TurnAwareProfile` 为什么存在;
# - 掌握上下文用量的**启发式估算**(CJK 感知)与分段报告;
# - 走进**强制压缩**:`/compact` 背后的 keep=6 策略、并发卸载、以及那个被"临时调参"的 SummarizationMiddleware。
#
# 涉及:`middleware/model_router.py`、`middleware/turn_model.py`、`llm/factory.py`、
# `context_usage.py`、`compaction.py`。

# %%
# —— 标准前置(每本 notebook 自带,便于独立阅读)——
import asyncio
import base64
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

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from octop_harness import HarnessAgent, HarnessAgentConfig, ModelConfig, ProviderConfig, init_workspace
from octop_harness.request import ChatRequest

from learning.support.fake_model import FakeChatModelFactory, FAKE_MODEL_REF

import logging
logging.getLogger("deepagents.middleware.skills").setLevel(logging.ERROR)

print("ok, 仓库根:", REPO)

# %% [markdown]
# ## 1. 优先级链:`resolve_turn_model_ref`
#
# 每一轮模型调用,`ModelRouterMiddleware`(2 号位)都会问一次"这轮用谁":

# %%
show("src/octop_harness/middleware/model_router.py", 1, 12)

# %% [markdown]
# 实现落在 `middleware/turn_model.py:52` 的 `resolve_turn_model_ref`,优先级从高到低:
#
# 1. `configurable["model"]`(调用方在 `ChatRequest.model` 指定,或 `/model` 斜杠写的每线程覆盖);
# 2. 用户的 `model_selector(state, config)` 钩子;
# 3. **多模态自动切换**:最新一条 HumanMessage 带非文本块(图片/音频/…)→ 换 `multimodal_model`;
# 4. `default_model`;
# 5. 第一个启用的模型(兜底)。
#
# ## 2. 实验:让中间件告诉我们"这轮选了谁"
#
# 复用 04 的侦察思路,但这次盯住 `configurable["model"]`(路由器每轮会把解析结果盖回去,
# `model_router.py:89-92`)。

# %%
class RouterSpy(AgentMiddleware[Any, Any]):
    """记录每轮路由决策的侦察中间件(同步/异步钩子成对定义,见 04 本的教训)。"""

    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str | None] = []

    def _record(self, request: ModelRequest) -> None:
        from octop_harness.middleware.runtime import runtime_config
        configurable = runtime_config(request).get("configurable", {})
        self.refs.append(configurable.get("model"))

    def wrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
        self._record(request)
        return handler(request)

    async def awrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
        self._record(request)
        return await handler(request)

# %%
# 双模型配置:文本默认 + 视觉模型(注意 input 模态)
def vision_providers() -> list[ProviderConfig]:
    return [
        ProviderConfig(
            id="fake",
            name="Fake Provider (offline)",
            base_url="http://127.0.0.1:9/v1",
            api_key="fake-key",
            models=[
                ModelConfig(id="fake-model", context_window=32_000),
                ModelConfig(id="vision", input=["text", "image"], context_window=64_000),
            ],
        )
    ]

WS = WORKSPACES / "nb05"
if WS.exists():
    shutil.rmtree(WS)
init_workspace(WS, language="zh")

spy = RouterSpy()
cfg = HarnessAgentConfig(
    workspace_dir=WS,
    providers=vision_providers(),
    default_model="fake/fake-model",
    multimodal_model="fake/vision",
    memory_enabled=False,
    web_search_tools=False,
    middleware=[spy],
)
factory = FakeChatModelFactory([
    "纯文本轮:默认模型。",
    "看图轮:应该切到视觉模型。",
    "覆盖轮:按显式指定。",
    "压缩前最后一轮。",
])
agent = HarnessAgent(cfg, model_factory=factory)

t = "r1"
await agent.call(ChatRequest(messages="纯文本提问", thread_id=t))
small_png = base64.b64encode(b"\x89PNG" + b"x" * 100).decode()   # 小图(<4KiB),不会触发媒体卸载
await agent.call(ChatRequest(messages=[{"role": "user", "content": [
    {"type": "text", "text": "看这张图"},
    {"type": "image", "base64": small_png, "mime_type": "image/png"},
]}], thread_id=t))
await agent.call(ChatRequest(messages="我要求用 vision 回答", thread_id=t, model="fake/vision"))

for i, ref in enumerate(spy.refs, 1):
    print(f"第 {i} 轮路由到:{ref}")

# %% [markdown]
# 三轮三种来源:默认 → 多模态自动切换 → 调用方显式指定。
# 注意假工厂对**任何** ref 都返回同一个脚本模型——这恰好证明了**路由决策与模型实例是解耦的**:
# 真实工厂里不同 ref 会命中不同缓存实例。
#
# `/model` 斜杠(03 本演示过)写的是**每线程持久覆盖**,底层是 `configurable["model"]`,
# 所以它天然排在优先级链第 1 位。
#
# ## 3. `ChatModelFactory`:缓存与驱逐
#
# `llm/factory.py`:按 `"{provider}/{model}"` ref 缓存实例;`pop_cached` 驱逐并关闭专用会话头客户端。
# manager 的 `add_provider/remove_provider` 就靠前缀 `"{provider}/"` 批量驱逐(manager.py:461-480)。
# 用**真工厂**离线验证缓存语义(构造 ChatOpenAI 不需要网络,调用才需要):

# %%
from octop_harness.llm.factory import ChatModelFactory

real_factory = ChatModelFactory(vision_providers())
m1 = real_factory.get_chat_model("fake/fake-model")
m2 = real_factory.get_chat_model("fake/fake-model")
print("同一 ref 两次获取是同一实例?", m1 is m2)

real_factory.pop_cached("fake/fake-model")
m3 = real_factory.get_chat_model("fake/fake-model")
print("驱逐后再取是新实例?", m3 is not m1)

print("list_refs:", real_factory.list_refs())
print("模型类型(注意是注入 reasoning 感知的子类):", type(m1).__name__)
real_factory.close()

# %% [markdown]
# `_build_openai` 构造的是 `_ReasoningAwareChatOpenAI`(`factory.py:392`):把 DeepSeek 风格的
# `reasoning_content` 在解析时搬进 `additional_kwargs`、序列化时再挂回去,避免二次调用报 400;
# 并强制 `stream_usage=True`(自定义 base_url 时 langchain-openai 会丢流式用量)。
# `_inject_model_token_limits`(`factory.py:583`)把 `max_input_tokens` 写进模型 profile——
# 这是下面 turn-aware profile 的伏笔。
#
# ## 4. `TurnAwareProfile`:让压缩阈值跟着"当轮模型"走
#
# 问题:deepagents 的 `SummarizationMiddleware` 在**编译时**用 seed model 的
# `profile["max_input_tokens"]` 算触发阈值(85% 触发/10% 保留),但运行时每轮可能换成别的模型
# ——阈值却还是 seed 的。解法(`middleware/turn_aware_profile.py`):给 seed 装一个
# **动态 profile**——一个 dict 子类,`get`/`__getitem__` 时按**同一套逐轮规则**重新解析当前模型,
# 再委托读取它的 profile:

# %%
show("src/octop_harness/middleware/turn_aware_profile.py", 33, 40)

# %%
# 语义现场验证:基座 dict 说 999,"当前轮模型"的 profile 说 12345 → 委托生效
from octop_harness.middleware.turn_aware_profile import TurnAwareProfile

scripted = factory.scripted
object.__setattr__(scripted, "profile", {"max_input_tokens": 12345})   # 模拟带 token 上限的模型
aware = TurnAwareProfile(
    {"max_input_tokens": 999},
    factory=factory,
    pick_default_ref=lambda: "fake/fake-model",
)
print("aware.get('max_input_tokens') =", aware.get("max_input_tokens"), "(← 委托到当前轮模型,而非基座 999)")
print("isinstance(aware, dict) =", isinstance(aware, dict), "(← 编译期 isinstance 检查不破)")

# %% [markdown]
# ## 5. 上下文用量:启发式估算器
#
# `context_usage.py` 不依赖 tokenizer,用**字符比率**估算:CJK 约 1.6 字符/token、拉丁 4.0、
# JSON 更密 3.0;图片按 1600、媒体 400 的平价块计。`ContextUsageMiddleware`(20 号位,
# 最后一个)把最终 ModelRequest 的分段快照盖到 AIMessage 上。

# %%
show("src/octop_harness/context_usage.py", 37, 50)

# %%
from octop_harness.context_usage import estimate_tokens

cjk = "你好世界" * 50            # 200 个 CJK 字符
latin = "hello world " * 15      # 195 个拉丁字符
print(f"CJK  {len(cjk)} 字符 → {estimate_tokens(cjk)} tokens(比率 ≈ {len(cjk)/estimate_tokens(cjk):.2f} 字符/token)")
print(f"拉丁 {len(latin)} 字符 → {estimate_tokens(latin)} tokens(比率 ≈ {len(latin)/estimate_tokens(latin):.2f} 字符/token)")

# %%
# 上一轮真实调用的分段报告(spy 那个 agent 的最后一轮)
hist = await agent.aget_history(t)
last_ai = next(m for m in reversed(hist) if m.__class__.__name__ == "AIMessage")
usage = last_ai.additional_kwargs.get("context_usage", {})
print(f"总量:{usage.get('used_tokens')}/{usage.get('max_tokens')} tokens")
print("分段:")
for k, v in (usage.get("segments") or {}).items():
    print(f"  {k:24s} {v}")

# %% [markdown]
# `tool_definitions` 往往是大头(工具 schema 也是上下文成本)——这也是渐进工具加载
# (`tool_search_mode`)存在的理由(15 本讲)。
#
# ## 6. 强制压缩:`/compact` 的背后
#
# `compaction.py` 的 `force_compact_thread` 驱动 `agent.acompact_conversation()`:
# - **keep=6**:强制保留最近 6 条(`FORCE_KEEP_MESSAGES`,比自动压缩的百分比更激进);
# - 不是新建 SummarizationMiddleware,而是**临时调参**被捕获的那个实例
#   (`_force_policy` 换 `helper.keep` / `helper.model` / `helper._summary_model`,完事恢复);
# - 历史卸载(写 `conversation_history/session_*.md`)与摘要 LLM **并发**跑(`asyncio.gather`);
# - 结果经 `graph.aupdate_state` 注入 `_summarization_event`,不产生新线程。

# %%
show("src/octop_harness/compaction.py", 148, 164)

# %%
# 离线 live:灌 8 轮对话 → 强制压缩
await agent.call(ChatRequest(messages="压缩前最后一问", thread_id=t))
before = len(await agent.aget_history(t))
result = await agent.acompact_conversation(t)
print(f"压缩前历史:{before} 条")
print(f"CompactResult: ok={result.ok} reason={result.reason}")
print(f"卸载文件:{result.display_path}")

offloaded = WS / result.display_path.lstrip("/")
if offloaded.exists():
    head = offloaded.read_text().splitlines()[:6]
    print("\n卸载文件开头:")
    print("\n".join("  " + line for line in head))

# %% [markdown]
# **诚实说明**:离线假模型下压缩"半程成功"——历史成功卸载落盘,但摘要为空:
# `_acreate_summary` 走的是 deepagents 摘要助手对模型的协议期望(结构化摘要调用),
# 脚本模型满足不了,于是按设计优雅降级(`CompactResult(ok=True)` + 空 summary,
# 图内消息替换也不触发)。这恰好暴露了一个事实:**摘要质量是压缩路径对真实 LLM 最强的依赖**。
# 接真实 Key 后 `/compact` 斜杠走同一套代码,可看到完整效果。
#
# ## 7. 思考题
#
# 1. 多模态自动切换为什么只看**最新一条** HumanMessage,而不是整个对话?
# 2. `pop_cached` 为什么要"关闭专用会话头客户端"?什么配置会创建专用客户端?(提示:`ProviderConfig.session_header`)
# 3. 压缩用"固定保留 6 条"而不是"百分比窗口",取舍是什么?(`compaction.py:35` 的注释)
# 4. `estimate_tokens` 的 CJK 比率 1.6 会在什么模型上明显偏差?偏差会影响哪些决策(阈值触发、`removed_tokens`)?
#
# ## 8. 延伸阅读
#
# - `tests/test_compaction*.py`、`tests/test_context_usage.py` —— 行为契约
# - `agent.py:1740-1764` —— 捕获 SummarizationMiddleware 的 monkeypatch(02 本看过,值得再看一遍)
# - 下一模块:[06_backend_workspace.ipynb](06_backend_workspace.ipynb) —— 存储与 SQL 之旅开始

# %%
await agent.aclose()
print("agent 已关闭;工作区保留在", WS)
