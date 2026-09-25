"""Deterministic ShruTea coaching fallback used when the LLM is unavailable."""

from __future__ import annotations


def template_commentary(drift_json: list[dict], reference_sequence: object = None) -> str:
    """Return one concise, evidence-based verdict without calling a network API."""
    if not drift_json:
        return "Clean take: every sung note stayed within the 20-cent threshold."

    worst = max(drift_json, key=lambda entry: abs(float(entry.get("cents_off", 0))))
    expected = worst.get("expected_note", "the target note")
    actual = worst.get("actual_note", expected)
    direction = worst.get("direction", "off")
    cents = abs(float(worst.get("cents_off", 0)))
    timestamp = float(worst.get("time", 0))
    landing = f"{expected} landed near {actual}" if actual != expected else f"{expected} sat"
    directions = [entry.get("direction") for entry in drift_json]
    if len(drift_json) > 1 and len(set(directions)) == 1:
        pattern = f" All {len(drift_json)} flagged notes were {directions[0]}, which points to support or monitoring rather than one slip."
    else:
        pattern = ""
    if cents >= 50:
        advice = "Re-sing the landing slowly, settle on the target before adding vibrato or grit."
    else:
        advice = "Loop that landing and aim for the target pitch before moving to the next phrase."
    return f"At {timestamp:.2f}s, {landing} {cents:.1f} cents {direction}.{pattern} {advice}"
