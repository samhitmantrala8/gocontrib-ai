"""Helpers shared across agent nodes."""

from __future__ import annotations

from pathlib import Path

from ..llm import LLM, LLMConfig


_LLM: LLM | None = None


def get_llm(config: dict) -> LLM:
    global _LLM
    if _LLM is not None:
        return _LLM
    llm_cfg = config.get("llm", {})
    kwargs = dict(
        provider=llm_cfg.get("provider", "gemini"),
        model=llm_cfg.get("model", "gemini-2.5-flash"),
        fallback_provider=llm_cfg.get("fallback_provider", "openrouter"),
        fallback_model=llm_cfg.get("fallback_model", "deepseek/deepseek-chat"),
        temperature=float(llm_cfg.get("temperature", 0.1)),
        max_output_tokens=int(llm_cfg.get("max_output_tokens", 4096)),
        request_timeout_seconds=int(llm_cfg.get("request_timeout_seconds", 60)),
    )
    if llm_cfg.get("gemini_models"):
        kwargs["gemini_models"] = list(llm_cfg["gemini_models"])
    if llm_cfg.get("openrouter_models"):
        kwargs["openrouter_models"] = list(llm_cfg["openrouter_models"])
    cfg = LLMConfig(**kwargs)
    _LLM = LLM(cfg)
    return _LLM


def reset_llm() -> None:
    global _LLM
    _LLM = None


def load_prompt(name: str) -> str:
    """Prompts live as standalone .md files so we can edit them without
    rebuilding the package or hunting through Python strings."""
    here = Path(__file__).resolve().parent.parent.parent.parent
    p = here / "prompts" / f"{name}.md"
    if not p.exists():
        # Fall back to in-package prompts dir if installed
        p2 = Path(__file__).resolve().parent.parent / "prompts" / f"{name}.md"
        if p2.exists():
            return p2.read_text(encoding="utf-8")
        raise FileNotFoundError(f"prompt {name} not found at {p}")
    return p.read_text(encoding="utf-8")


def trace(state: dict, node: str, **fields) -> None:
    state.setdefault("trace", []).append({"node": node, **fields})
