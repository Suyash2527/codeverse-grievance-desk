"""The simulated WhatsApp and phone-call channels, and Sarvam speech.

Guarantees under test:
  - the channels drive the same intake agent and the same confirm step, so a
    WhatsApp draft is still not a grievance until the citizen confirms it;
  - a case filed through a channel says so on its timeline, attributed to the
    citizen and to the mock-contacts rule;
  - an unknown channel name is rejected rather than stored;
  - speech never invents text: no provider means 503, a provider failure
    means 502, and nothing is ever filed from a guess;
  - no test reaches the network: Sarvam is replaced with fakes.
"""
from __future__ import annotations

import base64
import dataclasses

import httpx
import pytest
from sqlalchemy import func, select

import app.api.citizen as citizen_api
from app.models import AuditLog, Grievance
from app.services import intake_session, speech

COMPLAINT = (
    "There is an exposed electric wire hanging near the primary school in Loha, "
    "it is dangerous for the children."
)


def _grievances(session) -> int:
    return session.scalar(select(func.count()).select_from(Grievance))


@pytest.fixture
def with_sarvam(monkeypatch):
    """Configure a fake key on the settings the API module reads."""
    configured = dataclasses.replace(citizen_api.settings, sarvam_api_key="test-key-not-real")
    monkeypatch.setattr(citizen_api, "settings", configured)
    return configured


@pytest.fixture
def without_speech(monkeypatch):
    bare = dataclasses.replace(
        citizen_api.settings, sarvam_api_key=None, openai_api_key=None
    )
    monkeypatch.setattr(citizen_api, "settings", bare)
    return bare


class TestChannels:
    @pytest.mark.parametrize("channel", ["whatsapp", "call"])
    def test_a_channel_message_is_a_draft_not_a_grievance(
        self, client, loaded_session, channel
    ):
        body = client.post(
            "/api/intake/message",
            json={"text": COMPLAINT, "language": "en", "source": channel},
        ).json()
        assert body["ready_to_confirm"] is True
        assert body["transcript"][0]["source"] == channel
        assert _grievances(loaded_session) == 0, "nothing may be filed before confirm"

    def test_an_unknown_channel_is_rejected(self, client, loaded_session):
        response = client.post(
            "/api/intake/message",
            json={"text": COMPLAINT, "language": "en", "source": "telegram"},
        )
        assert response.status_code == 422
        assert _grievances(loaded_session) == 0

    @pytest.mark.parametrize(
        "channel,action", [("whatsapp", "RECEIVED_VIA_WHATSAPP"), ("call", "RECEIVED_VIA_CALL")]
    )
    def test_a_filed_case_records_its_channel(self, client, loaded_session, channel, action):
        first = client.post(
            "/api/intake/message",
            json={"text": COMPLAINT, "language": "en", "source": channel},
        ).json()
        filed = client.post(
            f"/api/intake/{first['session_key']}/confirm",
            json={"citizen_name": "Demo Citizen", "citizen_phone": "+91 00000 00001"},
        ).json()
        reference = filed["reference_no"]
        assert reference

        entry = loaded_session.scalar(
            select(AuditLog).where(AuditLog.target == reference, AuditLog.action == action)
        )
        assert entry is not None, "the channel must appear on the case's audit trail"
        assert entry.actor == "CITIZEN"
        assert entry.rule_applied == "RULE_8_MOCK_CONTACTS_ONLY"
        assert "simulated" in entry.reasoning

        timeline = client.get(f"/api/track/{reference}").json()["timeline"]
        assert any("received via" in step["action"] for step in timeline)

    def test_the_web_chat_records_no_channel_entry(self, client, loaded_session):
        first = client.post(
            "/api/intake/message", json={"text": COMPLAINT, "language": "en"}
        ).json()
        reference = client.post(
            f"/api/intake/{first['session_key']}/confirm", json={}
        ).json()["reference_no"]
        entries = loaded_session.scalars(
            select(AuditLog).where(
                AuditLog.target == reference, AuditLog.action.like("RECEIVED_VIA_%")
            )
        ).all()
        assert entries == []

    def test_the_channel_is_read_from_the_first_citizen_turn(self):
        transcript = [
            {"role": "system", "text": "hello"},
            {"role": "citizen", "text": "a", "source": "call"},
            {"role": "citizen", "text": "b", "source": "text"},
        ]
        assert intake_session.channel_of(transcript) == "call"
        assert intake_session.channel_of([]) == "text"

    def test_a_channel_sensitive_case_is_still_held_for_a_human(self, client, loaded_session):
        """The channel changes the door, not the rules behind it."""
        first = client.post(
            "/api/intake/message",
            json={"text": COMPLAINT, "language": "en", "source": "whatsapp"},
        ).json()
        filed = client.post(f"/api/intake/{first['session_key']}/confirm", json={}).json()
        assert filed["status"] != "AUTO_RESOLVE"


class TestSpeechEndpoints:
    def test_languages_report_no_speech_without_providers(self, client, without_speech):
        body = client.get("/api/intake/languages").json()
        assert body["voice_available"] is False
        assert body["tts_available"] is False
        assert body["speech_provider"] is None

    def test_languages_report_sarvam_when_configured(self, client, with_sarvam):
        body = client.get("/api/intake/languages").json()
        assert body["voice_available"] is True
        assert body["tts_available"] is True
        assert body["speech_provider"] == "sarvam"

    def test_speak_without_a_key_is_503_not_silence(self, client, without_speech):
        response = client.post("/api/intake/speak", json={"text": "Hello", "language": "en"})
        assert response.status_code == 503

    def test_speak_returns_wav_from_the_provider(self, client, with_sarvam, monkeypatch):
        seen = {}

        def fake(settings, text, *, language):
            seen.update(text=text, language=language)
            return b"RIFF....WAVEfmt "

        monkeypatch.setattr(speech, "synthesise", fake)
        response = client.post("/api/intake/speak", json={"text": "नमस्कार", "language": "mr"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert response.content.startswith(b"RIFF")
        assert seen == {"text": "नमस्कार", "language": "mr"}

    def test_speak_maps_a_provider_failure_to_502(self, client, with_sarvam, monkeypatch):
        def broken(settings, text, *, language):
            raise speech.SpeechUnavailable("text-to-speech returned 500")

        monkeypatch.setattr(speech, "synthesise", broken)
        assert client.post("/api/intake/speak", json={"text": "Hi"}).status_code == 502

    def test_transcribe_prefers_sarvam_when_configured(self, client, with_sarvam, monkeypatch):
        monkeypatch.setattr(
            speech, "transcribe", lambda settings, audio, **kw: "a wire has fallen near the school"
        )
        response = client.post(
            "/api/intake/transcribe",
            files={"audio": ("turn.webm", b"\x1aE\xdf\xa3fake", "audio/webm")},
            data={"language": "en"},
        )
        assert response.status_code == 200
        assert response.json()["text"] == "a wire has fallen near the school"
        assert response.json()["model"] == with_sarvam.sarvam_stt_model

    def test_transcribe_never_guesses_when_the_provider_fails(
        self, client, loaded_session, with_sarvam, monkeypatch
    ):
        def broken(settings, audio, **kw):
            raise speech.SpeechUnavailable("no speech was recognised in the clip")

        monkeypatch.setattr(speech, "transcribe", broken)
        response = client.post(
            "/api/intake/transcribe",
            files={"audio": ("turn.webm", b"\x1aE\xdf\xa3fake", "audio/webm")},
        )
        assert response.status_code == 502
        assert _grievances(loaded_session) == 0


class TestSarvamClient:
    """The HTTP client itself, against a fake transport."""

    def _settings(self, **over):
        return dataclasses.replace(citizen_api.settings, sarvam_api_key="k", **over)

    def test_tts_sends_the_documented_fields_and_decodes_audio(self, monkeypatch):
        captured = {}

        def fake_post(url, **kwargs):
            captured.update(url=url, **kwargs)
            return httpx.Response(200, json={"audios": [base64.b64encode(b"WAVDATA").decode()]})

        monkeypatch.setattr(speech.httpx, "post", fake_post)
        audio = speech.synthesise(self._settings(), "hello", language="hi")
        assert audio == b"WAVDATA"
        assert captured["url"] == speech.TTS_URL
        assert captured["headers"] == {"api-subscription-key": "k"}
        assert captured["json"]["language_code"] == "hi-IN"
        assert captured["json"]["text"] == "hello"
        assert "speaker" not in captured["json"], "unset speaker means provider default"

    def test_stt_sends_the_language_and_returns_the_transcript(self, monkeypatch):
        captured = {}

        def fake_post(url, **kwargs):
            captured.update(url=url, **kwargs)
            return httpx.Response(200, json={"transcript": "  पाणी नाही  "})

        monkeypatch.setattr(speech.httpx, "post", fake_post)
        text = speech.transcribe(
            self._settings(), b"clip", filename="a.webm", content_type="audio/webm", language="mr"
        )
        assert text == "पाणी नाही"
        assert captured["url"] == speech.STT_URL
        assert captured["data"]["language_code"] == "mr-IN"

    def test_an_empty_transcript_raises_instead_of_returning_nothing(self, monkeypatch):
        monkeypatch.setattr(
            speech.httpx, "post", lambda url, **kw: httpx.Response(200, json={"transcript": ""})
        )
        with pytest.raises(speech.SpeechUnavailable):
            speech.transcribe(
                self._settings(), b"clip", filename="a.webm", content_type=None, language="en"
            )

    def test_no_key_raises_before_any_request(self, monkeypatch):
        def must_not_run(*a, **k):
            raise AssertionError("no request may be made without a key")

        monkeypatch.setattr(speech.httpx, "post", must_not_run)
        bare = dataclasses.replace(citizen_api.settings, sarvam_api_key=None)
        with pytest.raises(speech.SpeechUnavailable):
            speech.synthesise(bare, "hello", language="en")

    def test_a_provider_error_status_raises(self, monkeypatch):
        monkeypatch.setattr(
            speech.httpx, "post", lambda url, **kw: httpx.Response(429, json={"error": "rate"})
        )
        with pytest.raises(speech.SpeechUnavailable):
            speech.synthesise(self._settings(), "hello", language="en")
