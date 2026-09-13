#!/usr/bin/env python3
"""Serve the ShruTea web companion and analyze rendered vocal takes.

Pitch detection is always local: the same capped drift.py command that feeds
the REAPER script is used here. When OPENAI_API_KEY is configured, the server
additionally sends a short, temporary audio excerpt to OpenAI for a transcript
and structured coaching. A failed or missing network integration never hides
the local pitch result.
"""

from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np
import certifi
from scipy.io import wavfile

try:
    from dotenv import load_dotenv
except ImportError:  # The local-only analyzer still works before optional UI deps are installed.
    load_dotenv = None

try:
    from openai import OpenAI, OpenAIError
except ImportError:  # Keep the local detector usable without an API SDK.
    OpenAI = None
    OpenAIError = Exception


UI_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = UI_DIRECTORY.parent
DRIFT_SCRIPT = REPOSITORY_ROOT / "drift.py"
DEMO_AUDIO = REPOSITORY_ROOT / "audio" / "Audio Only.wav"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
UI_ANALYSIS_SECONDS = 8
DEMO_TRANSCRIPT = "I held my breath, then found my way back home."
SUPPORTED_INPUT_SUFFIXES = {
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".ogg",
    ".wav",
    ".webm",
}
WAV_SUFFIX = ".wav"

FEEDBACK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "rhyme_scheme": {"type": "string"},
        "rhyme_feedback": {"type": "string"},
        "melody_feedback": {"type": "string"},
        "vibrato_feedback": {"type": "string"},
        "practice_steps": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 3,
        },
        "instrument_recommendations": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 4,
        },
    },
    "required": [
        "headline",
        "summary",
        "rhyme_scheme",
        "rhyme_feedback",
        "melody_feedback",
        "vibrato_feedback",
        "practice_steps",
        "instrument_recommendations",
    ],
}

if load_dotenv:
    load_dotenv(REPOSITORY_ROOT / ".env")

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from drift import REFERENCE_SEQUENCE  # noqa: E402
from commentary import template_commentary  # noqa: E402
from llm_coach import coach  # noqa: E402


def local_feedback(verdict: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Make every visible UI card useful when no LLM key is configured."""
    worst = max(results, key=lambda entry: float(entry["cents_off"]), default=None)
    if worst:
        note_detail = (
            f"{worst['expected_note']} landed near {worst['actual_note']} "
            f"({float(worst['cents_off']):.1f} cents off)."
        )
        melody_feedback = f"Loop the {worst['expected_note']} landing at {float(worst['time']):.2f}s, then sing it without vibrato."
        practice = [
            "Play the expected note and match it with a held vowel for four beats.",
            "Record one slow pass, listening for the note before adding style or grit.",
            "Use the REAPER marker to comp or re-sing only the flagged phrase.",
        ]
    else:
        note_detail = "No reference window crossed the 20-cent marker threshold."
        melody_feedback = "Keep this placement; use the clean take as the comp reference."
        practice = [
            "Save this take as a pitch reference before recording another pass.",
            "Keep the same monitor mix and vowel placement for the next section.",
            "Use REAPER markers only if a later phrase crosses the 20-cent threshold.",
        ]
    return {
        "headline": "Local pitch-coach plan",
        "summary": f"{verdict} {note_detail}",
        "rhyme_scheme": "Pitch-only REAPER session",
        "rhyme_feedback": "Local mode stays honest: it analyzes measured pitch and reference intent, not unverified lyric transcription.",
        "melody_feedback": melody_feedback,
        "vibrato_feedback": "Pitch windows are measured before making any claim about vocal vibrato.",
        "practice_steps": practice,
        "instrument_recommendations": [
            "A sustained reference tone for note matching",
            "A dry vocal monitor mix while re-singing the marker",
            "A gentle pad or piano to make the target pitch easy to hear",
        ],
    }


def mock_feedback(
    results: list[dict[str, Any]],
    genre: str,
    vocal_style: str,
) -> tuple[str, dict[str, Any]]:
    """Return clearly-labelled demo coaching when live AI is unavailable."""
    context = " / ".join(part for part in (genre, vocal_style) if part) or "your vocal style"
    worst = max(results, key=lambda entry: abs(float(entry["cents_off"])), default=None)
    landing = (
        f"The strongest marker is {worst['expected_note']} → {worst['actual_note']} at "
        f"{float(worst['time']):.2f}s ({float(worst['cents_off']):.0f}¢)."
        if worst
        else "No reference window crossed the 20-cent marker threshold."
    )
    transcript = (
        "Demo transcript preview — not transcribed from this take:\n"
        "“I held my breath, then found my way back home.”"
    )
    return transcript, {
        "headline": "Demo AI vocal-coach preview",
        "summary": f"{landing} For {context}, keep the phrase supported before adding grit.",
        "rhyme_scheme": "AABB · demo lyric sample",
        "rhyme_feedback": "The sample uses matching end sounds to make the hook feel settled. Replace this preview with a live transcript once a valid API key is configured.",
        "melody_feedback": "Approach the target note cleanly, hold it for two beats, then add the heavier tone on the release.",
        "vibrato_feedback": "Keep the first beat straight; introduce a light, even vibrato only after the note is centered.",
        "practice_steps": [
            "Sing the flagged landing on an open ‘ah’ with a piano reference.",
            "Repeat the phrase at 70% intensity, keeping the pitch stable before adding grit.",
            "Record one full-energy pass and compare it with the clean guide take.",
        ],
        "instrument_recommendations": [
            "Palm-muted electric-guitar riff for rhythmic weight",
            "Sub bass with a tight kick for the hip-hop foundation",
            "Wide distorted guitar or pad in the hook, leaving space for the vocal",
        ],
    }


def convert_to_wav(source_path: Path) -> Path:
    """Convert optional non-WAV input for local pYIN analysis."""
    if source_path.suffix.lower() == WAV_SUFFIX:
        return source_path
    if not shutil.which("ffmpeg"):
        raise ValueError("MP3/video needs FFmpeg. Render or upload WAV to analyze without extra setup.")
    converted_path = source_path.with_suffix(WAV_SUFFIX)
    completed = subprocess.run(
        ["ffmpeg", "-y", "-i", str(source_path), "-vn", "-ac", "1", "-ar", "44100", str(converted_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode:
        raise ValueError("Audio conversion failed. Render a WAV from REAPER or check FFmpeg.")
    return converted_path


def make_transcription_excerpt(wav_path: Path) -> Path:
    """Write a small, bounded WAV excerpt so transcription never uploads a whole song."""
    import librosa

    samples, sample_rate = librosa.load(
        wav_path,
        sr=16_000,
        mono=True,
        duration=UI_ANALYSIS_SECONDS,
    )
    if len(samples) == 0:
        raise ValueError("The selected take contains no readable audio.")
    excerpt = Path(tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name)
    wavfile.write(excerpt, sample_rate, (np.clip(samples, -1, 1) * 32767).astype(np.int16))
    return excerpt


def openai_feedback(
    wav_path: Path,
    results: list[dict[str, Any]],
    key: str,
    chords: str,
    genre: str,
    vocal_style: str,
) -> tuple[str, dict[str, Any]]:
    """Transcribe a bounded excerpt and request evidence-grounded JSON feedback."""
    if OpenAI is None:
        raise RuntimeError("OpenAI SDK is not installed. Run python3 -m pip install -r requirements.txt.")
    excerpt_path = make_transcription_excerpt(wav_path)
    try:
        client = OpenAI(timeout=15.0, max_retries=0)
        with excerpt_path.open("rb") as audio_file:
            transcript_response = client.audio.transcriptions.create(
                model=os.getenv("SHRUTEA_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"),
                file=audio_file,
            )
        transcript = transcript_response.text.strip()
        prompt = f"""You are ShruTea, an embedded vocal coach in a REAPER session.
Give concise, specific coaching based only on this supplied context. Do not claim
to hear pitch, vibrato, or melody beyond the local pitch-drift events. Treat
technique suggestions as optional coaching, not medical or professional advice.

Musical context: key={key or "not supplied"}; chords={chords or "not supplied"};
genre={genre or "not supplied"}; vocal style={vocal_style or "not supplied"}.
Transcript: {transcript or "[No intelligible lyrics were transcribed]"}
Measured local pitch-drift events: {json.dumps(results, separators=(",", ":"))}

Name a concrete note/cents event when one exists. Analyze rhyme only from the
transcript, and return the requested JSON fields."""
        response = client.responses.create(
            model=os.getenv("SHRUTEA_COACH_MODEL", "gpt-4o-mini"),
            input=prompt,
            max_output_tokens=500,
            store=False,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "shrutea_vocal_feedback",
                    "strict": True,
                    "schema": FEEDBACK_SCHEMA,
                }
            },
        )
        feedback = json.loads(response.output_text)
        if not isinstance(feedback, dict):
            raise ValueError("OpenAI returned an unexpected coaching format.")
        return transcript, feedback
    finally:
        excerpt_path.unlink(missing_ok=True)


def openrouter_verdict(
    results: list[dict[str, Any]],
    key: str,
    chords: str,
    genre: str,
    vocal_style: str,
) -> tuple[str, str]:
    """Ask a real OpenRouter model for a concise REAPER-aware coaching verdict."""
    model = os.getenv("SHRUTEA_OPENROUTER_MODEL", "openrouter/free")
    context = {
        "reference_sequence": REFERENCE_SEQUENCE,
        "drift_events": results,
        "musical_context": {
            "key": key or "not supplied",
            "chords": chords or "not supplied",
            "genre": genre or "not supplied",
            "vocal_style": vocal_style or "not supplied",
        },
    }
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "max_tokens": 160,
                "temperature": 0.2,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are ShruTea, an embedded vocal coach in a REAPER session. Give one concise, specific coaching verdict grounded only in supplied pitch evidence. Name the actual note and cents value when drift exists. Do not claim to hear lyrics, vibrato, or melody beyond the evidence. No generic encouragement.",
                    },
                    {"role": "user", "content": json.dumps(context, separators=(",", ":"))},
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
    certificate_context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=15, context=certificate_context) as response:
        payload = json.load(response)
    content = payload["choices"][0]["message"].get("content")
    if isinstance(content, list):
        verdict = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict)
        ).strip()
    else:
        verdict = str(content or "").strip()
    if not verdict or verdict.lower() == "none":
        raise ValueError("OpenRouter returned no coaching text.")
    return verdict, str(payload.get("model") or model)


def analyze_take(
    source_path: Path,
    key: str = "",
    chords: str = "",
    genre: str = "",
    vocal_style: str = "",
    demo: bool = False,
) -> dict[str, Any]:
    """Return local pitch results plus an optional network-enriched coach response."""
    analysis_path = convert_to_wav(source_path)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(DRIFT_SCRIPT),
                str(analysis_path),
                "--max-seconds",
                str(UI_ANALYSIS_SECONDS),
            ],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=45,
        )
        if completed.returncode:
            raise ValueError(completed.stderr.strip() or "drift.py failed.")
        results = json.loads(completed.stdout)
        if not isinstance(results, list):
            raise ValueError("drift.py did not return a JSON array.")
        # The browser's OpenAI route below returns the complete AI verdict.
        # Avoid paying for a redundant one-line coach call before it runs.
        uses_cloud_coach = bool(
            os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
        )
        verdict = (
            template_commentary(results, REFERENCE_SEQUENCE)
            if uses_cloud_coach
            else coach(results, REFERENCE_SEQUENCE)
        )
        payload: dict[str, Any] = {
            "results": results,
            "verdict": verdict,
            "reference_sequence": REFERENCE_SEQUENCE,
            "analysis_window_seconds": UI_ANALYSIS_SECONDS,
            "agent_mode": "Local ShruTea agent — no cloud required",
            "transcript": (
                DEMO_TRANSCRIPT
                if demo
                else "Not collected. This local-only session analyzes vocal pitch, reference intent, and REAPER marker actions."
            ),
            "feedback": local_feedback(verdict, results),
        }
        if os.environ.get("OPENROUTER_API_KEY"):
            try:
                live_verdict, model = openrouter_verdict(
                    results, key, chords, genre, vocal_style
                )
                live_feedback = local_feedback(live_verdict, results)
                live_feedback["headline"] = "OpenRouter live vocal coach"
                live_feedback["summary"] = live_verdict
                payload.update(
                    {
                        "verdict": live_verdict,
                        "feedback": live_feedback,
                        "agent_mode": f"OpenRouter live coach ({model})",
                    }
                )
            except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
                payload["agent_warning"] = f"OpenRouter coaching was unavailable; local drift coaching is still complete. ({error})"
            return payload
        if not os.environ.get("OPENAI_API_KEY"):
            transcript, feedback = mock_feedback(results, genre, vocal_style)
            payload.update(
                {
                    "transcript": transcript,
                    "feedback": feedback,
                    "verdict": feedback["summary"],
                    "agent_mode": "Demo coach — mock feedback",
                    "agent_warning": "Demo mode: showing a sample transcript and coaching plan. Add a valid API key later to enable live transcription.",
                }
            )
            return payload
        try:
            transcript, feedback = openai_feedback(
                analysis_path, results, key, chords, genre, vocal_style
            )
            payload.update(
                {
                    "transcript": transcript or "No intelligible lyrics were transcribed.",
                    "feedback": feedback,
                    "verdict": feedback["summary"],
                    "agent_mode": "OpenAI transcript + structured coaching",
                }
            )
        except (OSError, ValueError, json.JSONDecodeError, OpenAIError, RuntimeError) as error:
            transcript, feedback = mock_feedback(results, genre, vocal_style)
            payload.update(
                {
                    "transcript": transcript,
                    "feedback": feedback,
                    "verdict": feedback["summary"],
                    "agent_mode": "Demo coach — mock feedback",
                    "agent_warning": "Demo mode: showing a sample transcript and coaching plan. Add a valid API key later to enable live transcription.",
                }
            )
        return payload
    finally:
        if analysis_path != source_path:
            analysis_path.unlink(missing_ok=True)


class ShruTeaHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(UI_DIRECTORY), **kwargs)

    def send_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def parse_multipart(self, content_length: int) -> tuple[dict[str, str], str, bytes]:
        """Parse a multipart browser upload without the removed cgi module."""
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/"):
            raise ValueError("Expected a multipart audio upload.")

        header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n"
        message = BytesParser(policy=default).parsebytes(
            header.encode("utf-8") + self.rfile.read(content_length)
        )
        fields: dict[str, str] = {}
        filename = ""
        audio = b""
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            if name == "audio":
                filename = part.get_filename() or ""
                audio = part.get_payload(decode=True) or b""
            else:
                fields[name] = part.get_content().strip()
        return fields, filename, audio

    def do_POST(self) -> None:
        if self.path == "/api/demo":
            if not DEMO_AUDIO.is_file():
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "The bundled demo take was not found."})
                return
            try:
                self.send_json(
                    HTTPStatus.OK,
                    analyze_take(DEMO_AUDIO, genre="Demo vocal take", demo=True),
                )
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": f"Demo analysis failed: {error}"})
            return

        if self.path != "/api/analyze":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > MAX_UPLOAD_BYTES:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Choose an audio or video file smaller than 100 MB."})
            return
        if not self.headers.get_content_type().startswith("multipart/"):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Expected a multipart audio upload."})
            return

        try:
            fields, filename, audio = self.parse_multipart(content_length)
        except ValueError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        suffix = Path(filename).suffix.lower()
        if not audio or suffix not in SUPPORTED_INPUT_SUFFIXES:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Choose WAV, MP3, M4A, MP4, MOV, or another supported audio format."})
            return

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(audio)
        try:
            self.send_json(
                HTTPStatus.OK,
                analyze_take(
                    temporary_path,
                    key=fields.get("key", ""),
                    chords=fields.get("chords", ""),
                    genre=fields.get("genre", ""),
                    vocal_style=fields.get("vocal_style", ""),
                ),
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": f"Analysis failed: {error}"})
        finally:
            temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    print("ShruTea UI running at http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), ShruTeaHandler).serve_forever()
