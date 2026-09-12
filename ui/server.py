import cgi
import json
import os
import cgi
import json
import os
import subprocess
import sys
import tempfile
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from openai import OpenAI, OpenAIError
from dotenv import load_dotenv
UI_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = UI_DIRECTORY.parent
DRIFT_SCRIPT = REPOSITORY_ROOT / "drift.py"
load_dotenv(REPOSITORY_ROOT / ".env")
REPOSITORY_ROOT = UI_DIRECTORY.parent
DRIFT_SCRIPT = REPOSITORY_ROOT / "drift.py"
load_dotenv(REPOSITORY_ROOT / ".env")
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
TRANSCRIBABLE_SUFFIXES = {".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".wav", ".webm"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv"}
MAX_TRANSCRIPTION_BYTES = 24 * 1024 * 1024
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
        "practice_steps": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
        "instrument_recommendations": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 4},
    },
    "required": ["headline", "summary", "rhyme_scheme", "rhyme_feedback", "melody_feedback", "vibrato_feedback", "practice_steps", "instrument_recommendations"],
}

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

    @staticmethod
    def create_analysis_wav(source_path: Path) -> Path:
        """Convert non-WAV input to a temporary mono WAV for the local detector."""
        if source_path.suffix.lower() == ".wav":
            return source_path
        converted_path = source_path.with_suffix(".wav")
        completed = subprocess.run(
            ["ffmpeg", "-y", "-i", str(source_path), "-vn", "-ac", "1", "-ar", "44100", str(converted_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode:
            raise ValueError("Audio conversion failed. Install FFmpeg and make sure it is on PATH.")
        return converted_path

    @staticmethod
    def create_transcription_file(source_path: Path) -> Path:
        """Keep transcription uploads below the API size limit without changing local analysis."""
        if source_path.stat().st_size <= MAX_TRANSCRIPTION_BYTES:
            return source_path
        compressed_path = source_path.with_name(f"{source_path.stem}-transcription.mp3")
        completed = subprocess.run(
            ["ffmpeg", "-y", "-i", str(source_path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(compressed_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode or compressed_path.stat().st_size > MAX_TRANSCRIPTION_BYTES:
            raise ValueError("Could not prepare a transcription-sized audio file. Try a shorter take.")
        return compressed_path

    @staticmethod
    def create_feedback(transcript: str, drift_results: list[object], key: str, chords: str, genre: str, vocal_style: str) -> dict[str, object]:
        client = OpenAI()
        prompt = f"""You are ShruTea, an encouraging vocal coach for a developing singer. Create concise, specific feedback from the evidence below. Never claim you heard pitch, vibrato, or melody beyond the provided drift results and transcript. Treat every recommendation as optional coaching, not medical or professional diagnosis. Explain any uncertain inference plainly.

Musical context: key={key}; chords={chords}; genre={genre}; vocal style={vocal_style}.
Transcript: {transcript or '[No intelligible lyrics were transcribed]'}
Measured pitch-drift events from a local detector: {json.dumps(drift_results)}

Give usable technique instructions for melody and vibrato, analyze rhyme from the transcript only, and recommend instruments appropriate to the stated genre and vocal style. Mention chord drift only when detector events exist."""
        response = client.responses.create(
            model="gpt-4o-mini",
            input=prompt,
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
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Expected a multipart WAV upload."})
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"], "CONTENT_LENGTH": str(content_length)},
        )
        upload = form["audio"] if "audio" in form else None
        suffix = Path(str(upload.filename or "")).suffix.lower()
        if upload is None or not getattr(upload, "file", None) or suffix not in TRANSCRIBABLE_SUFFIXES | VIDEO_SUFFIXES:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Choose WAV, MP3, M4A, MP4, MOV, or another supported audio format."})
            return
        if not os.environ.get("OPENAI_API_KEY"):
            self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Set OPENAI_API_KEY before requesting transcription and AI coaching."})
            return

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(upload.file.read())
        analysis_path = temporary_path
        transcription_path = temporary_path
        try:
            analysis_path = self.create_analysis_wav(temporary_path)
            transcription_path = self.create_transcription_file(temporary_path)
            with transcription_path.open("rb") as audio_file:
                transcript_response = OpenAI().audio.transcriptions.create(model="gpt-4o-mini-transcribe", file=audio_file)
            transcript = transcript_response.text
            completed = subprocess.run(
                [sys.executable, str(DRIFT_SCRIPT), str(analysis_path)],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode:
                self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": completed.stderr.strip() or "drift.py failed."})
                return
            results = json.loads(completed.stdout)
            if not isinstance(results, list):
                raise ValueError("drift.py did not return a JSON array")
            feedback = self.create_feedback(
                transcript=transcript,
                drift_results=results,
                key=form.getfirst("key", "Not supplied"),
                chords=form.getfirst("chords", "Not supplied"),
                genre=form.getfirst("genre", "Not supplied"),
                vocal_style=form.getfirst("vocal_style", "Not supplied"),
            )
            self.send_json(HTTPStatus.OK, {"results": results, "transcript": transcript, "feedback": feedback})
        except (OSError, ValueError, json.JSONDecodeError, OpenAIError) as error:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Analysis failed: {error}"})
        finally:
            temporary_path.unlink(missing_ok=True)
            if analysis_path != temporary_path:
                analysis_path.unlink(missing_ok=True)
            if transcription_path not in {temporary_path, analysis_path}:
                transcription_path.unlink(missing_ok=True)
if __name__ == "__main__":
    print("ShruTea UI running at http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), ShruTeaHandler).serve_forever()
