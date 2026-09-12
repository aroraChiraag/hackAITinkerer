#!/usr/bin/env python3
"""LLM-backed ShruTea vocal-coach verdicts for a REAPER analysis session."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

from commentary import template_commentary


SYSTEM_PROMPT = """You are ShruTea, an embedded vocal coach inside a REAPER session.
You are given the reference melody the singer intended and the actual drift detected.
Reason briefly about what likely happened musically (for example, consistent flatness
can suggest a difficult reach or fatigue; an isolated dip can suggest a breath or
reach; no drift means a clean take) and give ONE concise, specific coaching verdict.
Do not give generic encouragement. Name the actual note and cents value when drift
exists. Return only the verdict, in at most two sentences, with at most one gentle
music or tea pun."""


def _claude_verdict(drift_json: list[dict], reference_sequence: object) -> str:
    from anthropic import Anthropic

    context = json.dumps(
        {"reference_sequence": reference_sequence, "drift_json": drift_json},
        separators=(",", ":"),
    )
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=5.0)
    response = client.messages.create(
        model=os.environ.get("SHRUTEA_CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=140,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Session context:\n{context}"}],
    )
    verdict = "".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()
    if not verdict:
        raise ValueError("Claude returned no text verdict")
    return verdict


def _openrouter_verdict(drift_json: list[dict], reference_sequence: object) -> str:
    """Use OpenRouter credits when a direct Anthropic key is not available."""
    context = json.dumps({"reference_sequence": reference_sequence, "drift_json": drift_json}, separators=(",", ":"))
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


def coach(drift_json: list[dict], reference_sequence: object) -> str:
    """Return an LLM verdict, falling back within five seconds on any failure."""
    fallback = template_commentary(drift_json, reference_sequence)
    direct_key = os.environ.get("ANTHROPIC_API_KEY")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if not direct_key and not openrouter_key:
        return fallback
    try:
        # Both provider implementations set a five-second client/request timeout.
        provider = _claude_verdict if direct_key else _openrouter_verdict
        return provider(drift_json, reference_sequence)
    except Exception:
        return fallback


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a ShruTea coaching verdict from drift JSON.")
    parser.add_argument("drift_json", type=Path, help="JSON file emitted by drift.py")
    args = parser.parse_args()
    try:
        drift_json = json.loads(args.drift_json.read_text(encoding="utf-8"))
        if not isinstance(drift_json, list):
            raise ValueError("drift JSON must be an array")
        from drift import REFERENCE_SEQUENCE

        print(coach(drift_json, REFERENCE_SEQUENCE))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"llm_coach.py: {error}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
