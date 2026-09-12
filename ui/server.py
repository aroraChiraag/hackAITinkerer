#!/usr/bin/env python3
"""ShruTea local server: pitch drift plus OpenAI vocal coaching."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

UI_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = UI_DIRECTORY.parent
DRIFT_SCRIPT = REPOSITORY_ROOT / "drift.py"
load_dotenv(REPOSITORY_ROOT / ".env")

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_TRANSCRIPTION_BYTES = 24 * 1024 * 1024
SUPPORTED_SUFFIXES = {".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".mov", ".mkv", ".ogg", ".wav", ".webm"}

FEEDBACK_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "headline": {"type": "string"}, "summary": {"type": "string"},
        "rhyme_scheme": {"type": "string"}, "rhyme_feedback": {"type": "string"},
        "melody_feedback": {"type": "string"}, "vibrato_feedback": {"type": "string"},
        "practice_steps": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
        "instrument_recommendations": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 4},
    },
    "required": ["headline", "summary", "rhyme_scheme", "rhyme_feedback", "melody_feedback", "vibrato_feedback", "practice_steps", "instrument_recommendations"],
}


class ShruTeaHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIRECTORY), **kwargs)

    def send_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def parse_multipart(self, content_length: int) -> tuple[dict[str, str], str, bytes]:
        """Parse the upload with email/MIME; cgi was removed in Python 3.13."""
        raw_body = self.rfile.read(content_length)
        headers = (f"Content-Type: {self.headers['Content-Type']}\r\nMIME-Version: 1.0\r\n\r\n").encode()
        message = BytesParser(policy=default).parsebytes(headers + raw_body)
        if not message.is_multipart():
            raise ValueError("Expected multipart form data.")
        fields: dict[str, str] = {}
        filename, audio_bytes = "", b""
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            payload = part.get_payload(decode=True) or b""
            if name == "audio" and part.get_filename():
                filename, audio_bytes = part.get_filename(), payload
            elif not part.get_filename():
                fields[name] = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if not filename or not audio_bytes:
            raise ValueError("Choose an audio or video file.")
        return fields, filename, audio_bytes

    @staticmethod
    def ffmpeg(arguments: list[str], error: str) -> None:
        result = subprocess.run(["ffmpeg", "-y", *arguments], capture_output=True, text=True, check=False)
        if result.returncode:
            raise ValueError(error)

    @classmethod
    def analysis_wav(cls, source: Path) -> Path:
        if source.suffix.lower() == ".wav":
            return source
        output = source.with_suffix(".wav")
        cls.ffmpeg(["-i", str(source), "-vn", "-ac", "1", "-ar", "44100", str(output)], "Audio conversion failed. Install FFmpeg and add it to PATH.")
        return output

    @classmethod
    def transcription_file(cls, source: Path) -> Path:
        if source.stat().st_size <= MAX_TRANSCRIPTION_BYTES:
            return source
        output = source.with_name(f"{source.stem}-transcription.mp3")
        cls.ffmpeg(["-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(output)], "Could not prepare a transcription-sized audio file.")
        if output.stat().st_size > MAX_TRANSCRIPTION_BYTES:
            raise ValueError("The compressed file is still too large. Try a shorter take.")
        return output

    @staticmethod
    def feedback(transcript: str, drift: list[object], fields: dict[str, str]) -> dict[str, object]:
        prompt = f"""You are ShruTea, an encouraging vocal coach. Use only the transcript and measured drift events below. Never claim you heard pitch, melody, or vibrato outside this data. Suggestions are optional coaching, not diagnosis.
Context: key={fields.get('key', 'Not supplied')}; chords={fields.get('chords', 'Not supplied')}; genre={fields.get('genre', 'Not supplied')}; vocal style={fields.get('vocal_style', 'Not supplied')}.
Transcript: {transcript or '[No intelligible lyrics]'}
Measured drift events: {json.dumps(drift)}
Give concise practice advice, analyze rhyme only from the transcript, and recommend instruments for the stated genre/style."""
        response = OpenAI().responses.create(
            model="gpt-4o-mini", input=prompt,
            text={"format": {"type": "json_schema", "name": "vocal_feedback", "strict": True, "schema": FEEDBACK_SCHEMA}},
        )
        return json.loads(response.output_text)

    def do_POST(self) -> None:
        if self.path != "/api/analyze":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > MAX_UPLOAD_BYTES:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Choose an audio or video file smaller than 100 MB."})
            return
        if not self.headers.get_content_type().startswith("multipart/"):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Expected a multipart upload."})
            return
        if not os.environ.get("OPENAI_API_KEY"):
            self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Add OPENAI_API_KEY to .env before analysis."})
            return

        temporary = analysis = transcription = None
        try:
            fields, filename, audio = self.parse_multipart(content_length)
            suffix = Path(filename).suffix.lower()
            if suffix not in SUPPORTED_SUFFIXES:
                raise ValueError("Choose WAV, MP3, M4A, MP4, MOV, or another supported audio format.")
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as file:
                temporary = Path(file.name)
                file.write(audio)
            analysis = self.analysis_wav(temporary)
            transcription = self.transcription_file(temporary)
            with transcription.open("rb") as audio_file:
                transcript = OpenAI().audio.transcriptions.create(model="gpt-4o-mini-transcribe", file=audio_file).text
            process = subprocess.run([sys.executable, str(DRIFT_SCRIPT), str(analysis)], cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False)
            if process.returncode:
                self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": process.stderr.strip() or "drift.py failed."})
                return
            drift = json.loads(process.stdout)
            if not isinstance(drift, list):
                raise ValueError("drift.py did not return a JSON array")
            self.send_json(HTTPStatus.OK, {"results": drift, "transcript": transcript, "feedback": self.feedback(transcript, drift, fields)})
        except (OSError, ValueError, json.JSONDecodeError, OpenAIError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": f"Analysis failed: {error}"})
        finally:
            for path in {temporary, analysis, transcription}:
                if path:
                    path.unlink(missing_ok=True)


if __name__ == "__main__":
    print("ShruTea UI running at http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), ShruTeaHandler).serve_forever()
