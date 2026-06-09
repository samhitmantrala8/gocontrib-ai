"""Provider-agnostic LLM client with multi-key rotation.

Why this shape:
* The agent makes many small LLM calls inside ReAct loops.
* Free-tier Gemini keys hit per-minute and per-day quotas quickly.
* Rotating across a pool of keys (and across models, and across providers)
  keeps long runs alive without needing the user to babysit them.

Resolution order on every call:

    Gemini key #0 model A
        -> on 429, try Gemini key #1 model A
        -> on 429, try Gemini key #N model A
        -> on 429, try Gemini key #0 model B (next in fallback_models)
        ...
        -> on 429 across the whole Gemini fleet,
           fall back to OpenRouter (key rotation, model rotation again)
        -> if everything 429s, raise LLMRateLimit so the caller can decide.

The user supplies keys via env. Multiple Gemini keys can be passed as a
comma-separated ``GEMINI_API_KEYS`` (preferred) or a single ``GEMINI_API_KEY``.
Same for ``OPENROUTER_API_KEYS`` / ``OPENROUTER_API_KEY``.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class LLMError(Exception):
    pass


class LLMRateLimit(LLMError):
    pass


@dataclass
class LLMConfig:
    provider: str = "gemini"
    model: str = "gemini-2.5-flash"
    fallback_provider: str = "openrouter"
    fallback_model: str = "deepseek/deepseek-chat"
    # Ordered list of Gemini models to try as we exhaust the key pool.
    gemini_models: list[str] = field(default_factory=lambda: [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.5-flash-lite",
        "gemini-flash-latest",
    ])
    openrouter_models: list[str] = field(default_factory=lambda: [
        "deepseek/deepseek-chat",
        "meta-llama/llama-3.3-70b-instruct",
        "google/gemini-flash-1.5",
        "openai/gpt-4o-mini",
    ])
    temperature: float = 0.1
    max_output_tokens: int = 4096
    request_timeout_seconds: int = 60


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in (
        "429", "rate limit", "quota", "exhausted", "resource_exhausted",
        "too many requests",
    ))


def _is_unsupported_model(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in (
        "is not found", "is not supported", "unknown model",
        "model_not_found", "404",
    ))


def _split_env(name_plural: str, name_single: str) -> list[str]:
    raw = os.getenv(name_plural) or os.getenv(name_single) or ""
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    return keys


# ---------------------------------------------------------------------------
# Gemini (single key + model)
# ---------------------------------------------------------------------------

class _GeminiSingle:
    def __init__(self, cfg: LLMConfig, api_key: str, model_name: str):
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self._genai = genai
        self._cfg = cfg
        self._model_name = model_name
        self._model = genai.GenerativeModel(model_name)

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        gen_cfg: dict[str, Any] = {
            "temperature": self._cfg.temperature,
            "max_output_tokens": self._cfg.max_output_tokens,
        }
        if json_mode:
            gen_cfg["response_mime_type"] = "application/json"

        prompt = f"{system}\n\n---\n\n{user}"
        try:
            resp = self._model.generate_content(prompt, generation_config=gen_cfg)
        except Exception as e:                                          # noqa: BLE001
            if _is_rate_limit(e):
                raise LLMRateLimit(str(e)) from e
            raise LLMError(f"[gemini:{self._model_name}] {e}") from e

        # The .text accessor raises if any candidate has a non-STOP
        # finish_reason (e.g. MAX_TOKENS, SAFETY). Walk parts manually.
        text = ""
        try:
            for c in getattr(resp, "candidates", None) or []:
                content = getattr(c, "content", None)
                for p in getattr(content, "parts", []) or []:
                    text += getattr(p, "text", "") or ""
        except Exception:                                               # noqa: BLE001
            pass
        if not text:
            try:
                text = getattr(resp, "text", None) or ""
            except Exception:                                           # noqa: BLE001
                text = ""
        if not text:
            fr = ""
            try:
                fr = str(resp.candidates[0].finish_reason) if resp.candidates else ""
            except Exception:                                           # noqa: BLE001
                pass
            raise LLMError(
                f"[gemini:{self._model_name}] empty response (finish_reason={fr})"
            )
        return text


# ---------------------------------------------------------------------------
# OpenRouter (single key + model)
# ---------------------------------------------------------------------------

class _OpenRouterSingle:
    def __init__(self, cfg: LLMConfig, api_key: str, model_name: str):
        from openai import OpenAI

        self._client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=cfg.request_timeout_seconds,
            default_headers={
                "HTTP-Referer": "https://github.com/samhitmantrala8/go-contributor-ai",
                "X-Title": "GoContrib-AI",
            },
        )
        self._cfg = cfg
        self._model_name = model_name

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        kwargs: dict[str, Any] = {
            "model": self._model_name,
            "temperature": self._cfg.temperature,
            "max_tokens": self._cfg.max_output_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as e:                                          # noqa: BLE001
            if _is_rate_limit(e):
                raise LLMRateLimit(str(e)) from e
            raise LLMError(f"[openrouter:{self._model_name}] {e}") from e
        return (resp.choices[0].message.content or "").strip()


# ---------------------------------------------------------------------------
# Public surface: rotates across keys * models * providers
# ---------------------------------------------------------------------------

class LLM:
    def __init__(self, cfg: LLMConfig):
        self._cfg = cfg
        self._gemini_keys = _split_env("GEMINI_API_KEYS", "GEMINI_API_KEY")
        self._openrouter_keys = _split_env("OPENROUTER_API_KEYS", "OPENROUTER_API_KEY")

        if not self._gemini_keys and not self._openrouter_keys:
            raise LLMError(
                "No LLM keys found. Set GEMINI_API_KEY(S) and/or "
                "OPENROUTER_API_KEY(S) in your .env."
            )

        # Build the ordered call plan once. Each entry is a thunk that, when
        # called, returns a fresh single-shot client. Building lazily keeps
        # imports cheap when a provider isn't used.
        self._plan: list[tuple[str, str, str]] = []
        for model in self._models_for("gemini"):
            for key in self._gemini_keys:
                self._plan.append(("gemini", key, model))
        for model in self._models_for("openrouter"):
            for key in self._openrouter_keys:
                self._plan.append(("openrouter", key, model))

        # Cache live clients so we don't rebuild per call.
        self._cache: dict[tuple[str, str, str], Any] = {}
        self._last_used: dict[tuple[str, str, str], float] = {}
        self._exhausted: set[tuple[str, str, str]] = set()
        self._exhaustion_cooldown_seconds = 60     # forget-and-retry after a minute

    def _models_for(self, provider: str) -> list[str]:
        if provider == "gemini":
            primary = [self._cfg.model] if self._cfg.provider == "gemini" else []
            tail = [m for m in self._cfg.gemini_models if m not in primary]
            return primary + tail
        if provider == "openrouter":
            primary = [self._cfg.fallback_model] if self._cfg.fallback_provider == "openrouter" else []
            tail = [m for m in self._cfg.openrouter_models if m not in primary]
            return primary + tail
        return []

    def _client(self, provider: str, key: str, model: str):
        sig = (provider, key, model)
        if sig in self._cache:
            return self._cache[sig]
        if provider == "gemini":
            client = _GeminiSingle(self._cfg, key, model)
        elif provider == "openrouter":
            client = _OpenRouterSingle(self._cfg, key, model)
        else:
            raise LLMError(f"unknown provider: {provider}")
        self._cache[sig] = client
        return client

    def _is_cooled_off(self, sig: tuple[str, str, str]) -> bool:
        if sig not in self._exhausted:
            return True
        last = self._last_used.get(sig, 0)
        return (time.monotonic() - last) > self._exhaustion_cooldown_seconds

    def _mark_exhausted(self, sig: tuple[str, str, str]) -> None:
        self._exhausted.add(sig)
        self._last_used[sig] = time.monotonic()

    @retry(
        retry=retry_if_exception_type(LLMError),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1.0, min=0.5, max=4),
        reraise=True,
    )
    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        last_err: Optional[Exception] = None
        for sig in self._plan:
            if not self._is_cooled_off(sig):
                continue
            try:
                client = self._client(*sig)
                return client.complete(system, user, json_mode=json_mode)
            except LLMRateLimit as e:
                self._mark_exhausted(sig)
                last_err = e
                continue
            except LLMError as e:
                if _is_unsupported_model(e):
                    # Skip and never retry this combo this run.
                    self._mark_exhausted(sig)
                    last_err = e
                    continue
                last_err = e
                continue
        raise LLMRateLimit(
            f"All {len(self._plan)} provider/key/model combos exhausted. "
            f"Last error: {last_err}"
        )

    def complete_json(self, system: str, user: str) -> dict:
        raw = self.complete(system, user, json_mode=True)
        return _parse_json_lenient(raw)


def _parse_json_lenient(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    start = raw.find("{")
    if start == -1:
        raise LLMError(f"No JSON object found in LLM output:\n{raw[:400]}")
    end = raw.rfind("}")
    if end != -1:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    # Truncated output: walk forward, count braces in non-string regions, and
    # close the object at the last balanced point we can find.
    repaired = _repair_truncated_json(raw[start:])
    if repaired is not None:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e:
            raise LLMError(
                f"JSON repair attempted but still invalid ({e}); raw[:400]={raw[:400]}"
            ) from e
    raise LLMError(f"No JSON object found in LLM output:\n{raw[:400]}")


def _repair_truncated_json(s: str) -> Optional[str]:
    depth = 0
    in_str = False
    escape = False
    last_balanced = -1
    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_balanced = i
    if last_balanced != -1:
        return s[: last_balanced + 1]
    # Object never closed: try to terminate the open string and close braces.
    end = s
    if in_str:
        end += '"'
    end += "}" * max(depth, 1)
    return end
