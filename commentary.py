"""Deterministic ShruTea coaching fallback used when the LLM is unavailable."""

from __future__ import annotations


def template_commentary(drift_json: list[dict], reference_sequence: object) -> str:
    """Return one concise, evidence-based verdict without calling a network API."""
    if not drift_json:
        return "Clean take: every voiced reference window stayed within the 20-cent threshold."

    worst = max(drift_json, key=lambda entry: abs(float(entry.get("cents_off", 0))))
    expected = worst.get("expected_note", "the reference note")
    actual = worst.get("actual_note", "the detected pitch")
    cents = abs(float(worst.get("cents_off", 0)))
    timestamp = float(worst.get("time", 0))
    if cents >= 50:
        advice = "Re-sing the landing slowly, settle on the reference before adding vibrato or grit."
    else:
        advice = "Loop that landing and aim for the reference pitch before moving to the next phrase."
    return f"At {timestamp:.2f}s, intended {expected} landed near {actual}, {cents:.1f} cents off. {advice}"
