#!/usr/bin/env python3
"""LLM-backed ShruTea vocal-coach verdicts for a REAPER analysis session."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

from commentary import template_commentary

try:
    from dotenv import load_dotenv
except ImportError:  # The template verdict still works without python-dotenv.
    load_dotenv = None

if load_dotenv:
    # REAPER does not inherit a terminal's environment, so read keys from .env.
    load_dotenv(Path(__file__).resolve().parent / ".env")


SYSTEM_PROMPT = """You are ShruTea, an embedded vocal coach inside a REAPER session.
You are given the analysis mode and the drift detected. In "reference" mode the
reference_sequence is the melody the singer intended; in "auto" mode each sung note
is compared with its nearest semitone. Each drift event says whether it was flat or sharp.
Reason briefly about what likely happened musically (for example, consistent flatness
can suggest a difficult reach or fatigue; an isolated dip can suggest a breath or
reach; no drift means a clean take) and give ONE concise, specific coaching verdict.
Do not give generic encouragement. Name the actual note, time, and cents value when
drift exists. Return only the verdict, in at most two sentences, with at most one
gentle music or tea pun."""


def session_context(drift_json: list[dict], mode: str, reference_sequence: object) -> str:
    context: dict[str, object] = {"mode": mode, "drift_json": drift_json}
    if mode == "reference":
        context["reference_sequence"] = reference_sequence
    return json.dumps(context, separators=(",", ":"))


def claude_text(system: str, prompt: str, max_tokens: int, schema: dict | None = None, timeout: float = 30.0) -> str:
    """Call Claude and return its text; with ``schema`` the text is guaranteed-valid JSON."""
    from anthropic import Anthropic

    model = os.environ.get("SHRUTEA_CLAUDE_MODEL", "claude-opus-5")
    request: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    output_config: dict = {}
    if "haiku" not in model:
        # Short coaching needs little reasoning. If a safety classifier declines,
        # "default" fallbacks re-run the request on Anthropic's recommended model.
        output_config["effort"] = "low"
        request["betas"] = ["server-side-fallback-2026-07-01"]
        request["fallbacks"] = "default"
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    if output_config:
        request["output_config"] = output_config

    client = Anthropic(timeout=timeout, max_retries=1)
    response = client.beta.messages.create(**request)
    if response.stop_reason == "refusal":
        raise ValueError("Claude declined this request")
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise ValueError(f"Claude returned no text (stop reason: {response.stop_reason})")
    return text


def _claude_verdict(context: str) -> str:
    return claude_text(SYSTEM_PROMPT, f"Session context:\n{context}", max_tokens=2000)


def _openai_verdict(context: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=5.0, max_retries=0)
    response = client.responses.create(
        model=os.environ.get("SHRUTEA_COACH_MODEL", "gpt-4o-mini"),
        instructions=SYSTEM_PROMPT,
        input="Session context: " + context,
        max_output_tokens=140,
        store=False,
    )
    verdict = response.output_text.strip()
    if not verdict:
        raise ValueError("OpenAI returned no text verdict")
    return verdict


def _openrouter_verdict(context: str) -> str:
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(
            {
                "model": os.environ.get("SHRUTEA_OPENROUTER_MODEL", "anthropic/claude-haiku-4.5"),
                "max_tokens": 140,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Session context:\n{context}"},
                ],
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
            "X-OpenRouter-Title": "ShruTea",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5.0) as response:
        body = json.load(response)
    verdict = body["choices"][0]["message"]["content"].strip()
    if not verdict:
        raise ValueError("OpenRouter returned no text verdict")
    return verdict


# Tried in order; the first provider with a configured key is used.
PROVIDERS = (
    ("OPENAI_API_KEY", _openai_verdict),
    ("ANTHROPIC_API_KEY", _claude_verdict),
    ("OPENROUTER_API_KEY", _openrouter_verdict),
)


def coach(drift_json: list[dict], reference_sequence: object = None, mode: str = "auto") -> str:
    """Return an LLM verdict, falling back to the local template on any failure."""
    fallback = template_commentary(drift_json, reference_sequence)
    provider = next((function for key, function in PROVIDERS if os.environ.get(key)), None)
    if provider is None:
        return fallback
    try:
        # Every provider sets a client/request timeout, so REAPER never hangs.
        return provider(session_context(drift_json, mode, reference_sequence))
    except Exception as error:
        print(f"llm_coach.py: {provider.__name__} failed, using local verdict: {error}", file=sys.stderr)
        return fallback


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a ShruTea coaching verdict from drift JSON.")
    parser.add_argument("drift_json", type=Path, help="JSON file emitted by drift.py")
    parser.add_argument("--mode", choices=("auto", "reference"), default="auto", help="mode drift.py ran in")
    args = parser.parse_args()
    try:
        drift_json = json.loads(args.drift_json.read_text(encoding="utf-8"))
        if not isinstance(drift_json, list):
            raise ValueError("drift JSON must be an array")
        from drift import REFERENCE_SEQUENCE

        print(coach(drift_json, REFERENCE_SEQUENCE, args.mode))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"llm_coach.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
