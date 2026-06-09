"""Probe every Gemini and OpenRouter model in the config to see which ones
this account can actually call. Prints a table; exits non-zero only if every
model fails."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from go_contributor.llm import (   # noqa: E402
    LLMConfig,
    LLMError,
    LLMRateLimit,
    _GeminiSingle,
    _OpenRouterSingle,
    _split_env,
)


PROMPT_USER = "Reply with the single word OK and nothing else."
PROMPT_SYS = "You are a probe. Be terse."


def _row(name: str, ok: bool, latency_ms: int, note: str) -> str:
    status = "PASS" if ok else "FAIL"
    return f"{status:5}  {latency_ms:6}ms  {name:48}  {note}"


def probe_gemini(cfg: LLMConfig, keys: list[str], models: list[str]) -> list[dict]:
    rows: list[dict] = []
    for model in models:
        for i, key in enumerate(keys):
            label = f"gemini:{model}#key{i}"
            t0 = time.monotonic()
            try:
                client = _GeminiSingle(cfg, key, model)
                out = client.complete(PROMPT_SYS, PROMPT_USER)
                ok = "ok" in out.strip().lower()
                rows.append({
                    "name": label, "ok": ok, "ms": int((time.monotonic() - t0) * 1000),
                    "note": out.strip()[:60],
                })
            except LLMRateLimit as e:
                rows.append({
                    "name": label, "ok": False, "ms": int((time.monotonic() - t0) * 1000),
                    "note": "RATE-LIMITED: " + str(e)[:80],
                })
            except LLMError as e:
                rows.append({
                    "name": label, "ok": False, "ms": int((time.monotonic() - t0) * 1000),
                    "note": str(e)[:90],
                })
    return rows


def probe_openrouter(cfg: LLMConfig, keys: list[str], models: list[str]) -> list[dict]:
    rows: list[dict] = []
    for model in models:
        for i, key in enumerate(keys):
            label = f"openrouter:{model}#key{i}"
            t0 = time.monotonic()
            try:
                client = _OpenRouterSingle(cfg, key, model)
                out = client.complete(PROMPT_SYS, PROMPT_USER)
                ok = "ok" in out.strip().lower()
                rows.append({
                    "name": label, "ok": ok, "ms": int((time.monotonic() - t0) * 1000),
                    "note": out.strip()[:60],
                })
            except LLMRateLimit as e:
                rows.append({
                    "name": label, "ok": False, "ms": int((time.monotonic() - t0) * 1000),
                    "note": "RATE-LIMITED: " + str(e)[:80],
                })
            except LLMError as e:
                rows.append({
                    "name": label, "ok": False, "ms": int((time.monotonic() - t0) * 1000),
                    "note": str(e)[:90],
                })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--report", default=str(ROOT / "docs" / "model_probe_results.txt"))
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    with open(args.config, "r", encoding="utf-8") as f:
        cfg_yaml = yaml.safe_load(f)

    cfg = LLMConfig(
        provider=cfg_yaml["llm"]["provider"],
        model=cfg_yaml["llm"]["model"],
        gemini_models=cfg_yaml["llm"]["gemini_models"],
        openrouter_models=cfg_yaml["llm"]["openrouter_models"],
        temperature=0.0,
        max_output_tokens=512,           # 2.5-flash uses tokens for "thinking"
        request_timeout_seconds=30,
    )

    gem_keys = _split_env("GEMINI_API_KEYS", "GEMINI_API_KEY")
    or_keys = _split_env("OPENROUTER_API_KEYS", "OPENROUTER_API_KEY")
    print(f"Found {len(gem_keys)} Gemini key(s), {len(or_keys)} OpenRouter key(s)")

    rows: list[dict] = []
    if gem_keys:
        rows += probe_gemini(cfg, gem_keys, cfg.gemini_models)
    if or_keys:
        rows += probe_openrouter(cfg, or_keys, cfg.openrouter_models)

    header = f"{'STATUS':5}  {'LAT':>8}  {'NAME':48}  NOTE"
    sep = "-" * 130
    body = "\n".join(_row(r["name"], r["ok"], r["ms"], r["note"]) for r in rows)
    out = f"{header}\n{sep}\n{body}\n"
    print(out)

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(out)

    pass_count = sum(1 for r in rows if r["ok"])
    print(f"\n{pass_count}/{len(rows)} model+key combos working")
    return 0 if pass_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
