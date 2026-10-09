"""Demo runtime: one HarnessAgentManager plus agents built from agents.json / env.

Provider credentials come from ``chat_demo/.env`` (loaded here) or the process
environment; the harness detects them via
``octop_harness.config.env.detect_providers_from_env`` when each agent is built.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from octop_harness.config import HarnessAgentConfig
from octop_harness.manager import HarnessAgentManager
from octop_harness.security.models import SecurityPolicy

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent

FAKE_REPLY = "Hello! This is a **fake** streamed reply (CHAT_DEMO_FAKE_MODEL=1) — the pipeline works."

_runtime: DemoRuntime | None = None


def install_fake_model() -> None:
    """Swap the OpenAI model builder for a fake model (offline UI demo / smoke).

    Provider detection still requires a dummy key (``OPENAI_API_KEY=sk-fake``);
    the fake model never touches the network.
    """
    import itertools

    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    from octop_harness.llm import factory

    class _FakeChatModel(GenericFakeChatModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> _FakeChatModel:
            return self

    def _fake_build(provider: Any, model: Any) -> GenericFakeChatModel:
        return _FakeChatModel(messages=itertools.cycle([FAKE_REPLY]))

    factory._build_openai = _fake_build
    logger.warning("CHAT_DEMO_FAKE_MODEL=1 — OpenAI builder replaced with a fake model")


class DemoRuntime:
    """Owns the manager singleton and the demo agent registry."""

    def __init__(self, root: Path = ROOT_DIR) -> None:
        self.root = root
        load_dotenv(root / ".env")
        if os.environ.get("CHAT_DEMO_FAKE_MODEL") == "1":
            install_fake_model()
        self.manager = HarnessAgentManager(log_dir=root / "logs")
        self._setup_agents()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _load_spec(self) -> dict[str, Any]:
        spec_path = self.root / "agents.json"
        if not spec_path.exists():
            return {}
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        if isinstance(spec, list):  # bare list of agent defs
            return {"agents": spec}
        if isinstance(spec, dict):
            return spec
        raise TypeError(f"agents.json must be an object or list, got {type(spec).__name__}")

    def _setup_agents(self) -> None:
        spec = self._load_spec()
        agent_defs = spec.get("agents") or [{"name": "demo"}]
        for agent_def in agent_defs:
            self._create_agent(agent_def)
        if spec.get("hitl"):
            # One manager-wide policy; rebuilds every registered agent.
            self.manager.set_security_policy(SecurityPolicy.from_dict({"hitl": {"enabled": True}}))

    def _create_agent(self, agent_def: dict[str, Any]) -> str:
        name = str(agent_def.get("name") or "demo")
        workspace = Path(agent_def.get("workspace_dir") or (self.root / "workspace" / name))
        if not workspace.is_absolute():
            workspace = (self.root / workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)

        kwargs: dict[str, Any] = {}
        for key in ("default_model", "system_prompt", "backend", "language"):
            if agent_def.get(key) is not None:
                kwargs[key] = agent_def[key]
        config = HarnessAgentConfig.from_env(workspace_dir=workspace, name=name, **kwargs)
        self._resolve_providers(config, [str(ref) for ref in agent_def.get("models") or []])
        entry = self.manager.create_agent(config)
        logger.info("chat demo agent %r registered as %s (workspace=%s)", name, entry.agent_id, workspace)
        return entry.agent_id

    def _resolve_providers(self, config: HarnessAgentConfig, extra_refs: list[str]) -> None:
        """Pre-resolve env providers so referenced model ids beyond the presets work.

        Preset catalogs (``providers/provider_template.json``) lag behind vendor
        model releases — e.g. Ark ships ``deepseek-v4-1-flash-260910`` while the
        ``volcengine-cn`` preset only lists older ids. Any ``<provider>/<model>``
        reference (``HARNESS_DEFAULT_MODEL``, an agent's ``default_model``, or
        ``agents.json`` ``models``) that names a known provider but an unknown
        model id is registered as-is, with a warning.
        """
        from octop_harness.config import ModelConfig
        from octop_harness.config.env import detect_providers_from_env

        providers, detected_default = detect_providers_from_env()
        if not providers:
            return  # let HarnessAgent raise its own "requires providers" error
        refs = set(extra_refs)
        if config.default_model:
            refs.add(config.default_model)
        elif detected_default is not None:
            config.default_model = detected_default
            refs.add(detected_default)

        by_id = {provider.id: provider for provider in providers}
        for ref in refs:
            provider_id, _, model_id = ref.partition("/")
            provider = by_id.get(provider_id)
            if provider is None or not model_id or provider.get_model(model_id) is not None:
                continue
            provider.models = [*provider.models, ModelConfig(id=model_id, name=model_id)]
            logger.warning(
                "model %r is not in the bundled preset catalog; registering it as configured",
                ref,
            )
        config.providers = providers

    # ------------------------------------------------------------------
    # Payloads
    # ------------------------------------------------------------------

    def agents_payload(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for entry in self.manager.list_agents():
            config = entry.config
            models: list[dict[str, Any]] = []
            for provider in config.providers:
                for model in provider.enabled_models():
                    models.append(
                        {
                            "ref": f"{provider.id}/{model.id}",
                            "provider": provider.id,
                            "id": model.id,
                            "name": model.name,
                            "context_window": model.effective_context_window,
                        }
                    )
            try:
                default_model = config.pick_default_model_ref()
            except ValueError:
                default_model = None
            out.append(
                {
                    "agent_id": entry.agent_id,
                    "name": config.name,
                    "default_model": default_model,
                    "models": models,
                }
            )
        return out


def get_runtime() -> DemoRuntime:
    global _runtime
    if _runtime is None:
        _runtime = DemoRuntime()
    return _runtime
