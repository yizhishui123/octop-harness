"""离线脚本化聊天模型 + 假工厂 —— learning notebook 的核心基础设施。

真实流程类 notebook(03/04/05 等)需要在**零 API Key、零网络**的前提下把
``HarnessAgent`` 的完整图跑起来。做法:

1. ``ScriptedChatModel`` —— 一个 ``BaseChatModel`` 子类,按顺序回放预先编排的
   ``AIMessage``(纯文本或带 ``tool_calls``),脚本用尽后返回兜底消息。
2. ``FakeChatModelFactory`` —— 继承 ``ChatModelFactory``,只覆写
   ``get_chat_model``;ref 解析(``"auto"``、``"fake/fake-model"``、角色绑定)
   完全沿用生产实现,因此模型路由、turn-aware profile 等路径都与生产一致。
3. 通过 ``HarnessAgent(model_factory=...)`` 注入点(``agent.py`` 构造参数)
   替换模型来源,其余组装(中间件、后端、checkpointer、工具)全部真实。

notebook 中的用法::

    from learning.support.fake_model import FakeChatModelFactory, FAKE_MODEL_REF

    factory = FakeChatModelFactory(["你好,我是假模型。", ...])
    agent = HarnessAgent(config, model_factory=factory)
    await agent.call("hi")
"""

from __future__ import annotations

from collections import deque
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from octop_harness.config import HarnessAgentConfig, ModelConfig, ProviderConfig
from octop_harness.llm.factory import ChatModelFactory

FAKE_PROVIDER_ID = "fake"
FAKE_MODEL_ID = "fake-model"
FAKE_MODEL_REF = f"{FAKE_PROVIDER_ID}/{FAKE_MODEL_ID}"


class ScriptedChatModel(BaseChatModel):
    """按顺序回放脚本消息的假模型。

    所有获取该模型的代码拿到的都是**同一个实例**(共享一个队列),因此
    ``ModelRouterMiddleware`` 每轮重新取模型也不会重置脚本进度——与真实
    工厂"每个 ref 一个缓存实例"的语义一致。
    """

    queue: Any = None
    fallback: str = "(脚本已用尽——请在 FakeChatModelFactory 里追加更多回复)"

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        # 假模型不解析工具 schema,直接返回自身,保证 bind 后仍可调用。
        return self

    def _generate(
        self,
        messages: Any,
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        message: AIMessage | None = None
        if self.queue:
            item = self.queue.popleft()
            message = AIMessage(content=item) if isinstance(item, str) else item
        if message is None:
            message = AIMessage(content=self.fallback)
        return ChatResult(generations=[ChatGeneration(message=message)])


def fake_providers() -> list[ProviderConfig]:
    """构造一个离线假 Provider(base_url 永远不会被访问)。"""
    return [
        ProviderConfig(
            id=FAKE_PROVIDER_ID,
            name="Fake Provider (offline)",
            base_url="http://127.0.0.1:9/v1",
            api_key="fake-key",
            models=[ModelConfig(id=FAKE_MODEL_ID, context_window=32_000)],
        ),
    ]


class FakeChatModelFactory(ChatModelFactory):
    """每个模型引用都返回同一个 :class:`ScriptedChatModel` 的假工厂。

    继承自 ``ChatModelFactory``:``resolve_ref`` / ``get`` / ``get_for`` /
    ``resolve_for_turn`` 等全部沿用生产实现,仅替换 ``get_chat_model``。
    """

    def __init__(
        self,
        script: list[str | AIMessage],
        *,
        agent_config: HarnessAgentConfig | None = None,
    ) -> None:
        super().__init__(fake_providers(), agent_config=agent_config)
        self._scripted = ScriptedChatModel(queue=deque(script))

    def get_chat_model(self, model_ref: str) -> BaseChatModel:
        return self._scripted

    @property
    def scripted(self) -> ScriptedChatModel:
        """暴露脚本队列,便于 notebook 观察/推进进度。"""
        return self._scripted


__all__ = [
    "FAKE_MODEL_ID",
    "FAKE_MODEL_REF",
    "FAKE_PROVIDER_ID",
    "FakeChatModelFactory",
    "ScriptedChatModel",
    "fake_providers",
]
