"""Speech for the simulated phone-call and WhatsApp voice channels.

Sarvam is used because it handles Marathi and Hindi natively in both
directions. It is optional: every caller of this module must cope with
`SpeechUnavailable`, and the channels fall back to typed text.

Two rules this module keeps:
  - it never invents a transcript. A failed or empty transcription raises, so
    a wrong guess can never become a filed grievance;
  - the API key is read from settings (the environment) and never logged.
"""
from __future__ import annotations

import base64

import httpx

from app.config import Settings

STT_URL = "https://api.sarvam.ai/speech-to-text"
TTS_URL = "https://api.sarvam.ai/text-to-speech"

# Sarvam takes BCP-47 codes; the app uses two-letter ones.
LANGUAGE_CODES = {"en": "en-IN", "hi": "hi-IN", "mr": "mr-IN"}

#: Sarvam's synchronous STT accepts clips under 30 seconds.
MAX_CLIP_BYTES = 6 * 1024 * 1024
#: Sarvam's bulbul:v3 accepts up to 2500 characters per request.
MAX_TTS_CHARS = 2500

TIMEOUT = httpx.Timeout(45.0, connect=10.0)


class SpeechUnavailable(RuntimeError):
    """Speech is not configured, or the provider failed. Callers fall back to text."""


def available(settings: Settings) -> bool:
    return bool(settings.sarvam_api_key)


def _headers(settings: Settings) -> dict[str, str]:
    if not settings.sarvam_api_key:
        raise SpeechUnavailable("SARVAM_API_KEY is not configured")
    return {"api-subscription-key": settings.sarvam_api_key}


def _language(code: str) -> str:
    return LANGUAGE_CODES.get(code, "en-IN")


def transcribe(
    settings: Settings,
    audio: bytes,
    *,
    filename: str,
    content_type: str | None,
    language: str,
) -> str:
    """Speech to text. Raises rather than returning a guessed transcript."""
    if not audio:
        raise ValueError("the audio clip is empty")
    if len(audio) > MAX_CLIP_BYTES:
        raise ValueError("the audio clip is too long; keep each turn under 30 seconds")

    try:
        response = httpx.post(
            STT_URL,
            headers=_headers(settings),
            files={"file": (filename, audio, content_type or "application/octet-stream")},
            data={"model": settings.sarvam_stt_model, "language_code": _language(language)},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise SpeechUnavailable(f"speech-to-text request failed: {exc.__class__.__name__}") from exc
    if response.status_code != 200:
        raise SpeechUnavailable(f"speech-to-text returned {response.status_code}")

    transcript = (response.json().get("transcript") or "").strip()
    if not transcript:
        raise SpeechUnavailable("no speech was recognised in the clip")
    return transcript


def synthesise(settings: Settings, text: str, *, language: str) -> bytes:
    """Text to speech, returned as WAV bytes."""
    text = text.strip()
    if not text:
        raise ValueError("nothing to speak")
    if len(text) > MAX_TTS_CHARS:
        raise ValueError(f"text is longer than {MAX_TTS_CHARS} characters")

    body: dict[str, object] = {
        "text": text,
        "language_code": _language(language),
        "model": settings.sarvam_tts_model,
        "speech_sample_rate": 24000,
        "output_audio_codec": "wav",
    }
    if settings.sarvam_tts_speaker:
        body["speaker"] = settings.sarvam_tts_speaker

    try:
        response = httpx.post(TTS_URL, headers=_headers(settings), json=body, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise SpeechUnavailable(f"text-to-speech request failed: {exc.__class__.__name__}") from exc
    if response.status_code != 200:
        raise SpeechUnavailable(f"text-to-speech returned {response.status_code}")

    audios = response.json().get("audios") or []
    if not audios:
        raise SpeechUnavailable("text-to-speech returned no audio")
    return base64.b64decode(audios[0])
