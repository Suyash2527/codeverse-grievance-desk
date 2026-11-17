"""Citizen chat, tracking and dispute.

The guarantee under test: no grievance exists until the citizen confirms the
draft, and what is filed is exactly the draft they were shown.
"""
from __future__ import annotations

from sqlalchemy import func, select

from app.models import AuditLog, CategoryMaster, Grievance, IntakeSession
from app.services import geo, intake_session

MARATHI = "मुखेड टाउन मध्ये पाण्याची पाइपलाइन फुटली आहे"
HINDI = "मुखेड में पानी की पाइपलाइन टूट गई है"
ENGLISH = "There is a pipeline leakage wasting water"


def _count_grievances(session) -> int:
    return session.scalar(select(func.count()).select_from(Grievance))


class TestDraftBeforeTicket:
    def test_a_message_creates_a_session_not_a_grievance(self, client, loaded_session):
        body = client.post(
            "/api/intake/message", json={"text": ENGLISH, "language": "en"}
        ).json()
        assert body["session_key"].startswith("ses_")
        assert body["draft"]
        assert _count_grievances(loaded_session) == 0, "nothing may be filed yet"

    def test_missing_details_are_asked_for(self, client, loaded_session):
        body = client.post(
            "/api/intake/message", json={"text": ENGLISH, "language": "en"}
        ).json()
        assert body["ready_to_confirm"] is False
        assert body["missing_details"]

    def test_a_follow_up_answer_refines_the_same_draft(self, client, loaded_session):
        first = client.post(
            "/api/intake/message", json={"text": ENGLISH, "language": "en"}
        ).json()
        second = client.post(
            "/api/intake/message",
            json={
                "text": "It is in Mukhed Town",
                "language": "en",
                "session_key": first["session_key"],
            },
        ).json()
        assert second["session_key"] == first["session_key"]
        assert second["draft"]["taluka"] == "Mukhed"
        assert second["draft"]["locality"] == "Mukhed Town"
        assert second["ready_to_confirm"] is True
        assert _count_grievances(loaded_session) == 0

    def test_confirmation_creates_exactly_one_grievance(self, client, loaded_session):
        first = client.post(
            "/api/intake/message",
            json={"text": f"{ENGLISH} in Mukhed Town", "language": "en"},
        ).json()
        result = client.post(
            f"/api/intake/{first['session_key']}/confirm",
            json={"citizen_name": "Demo Citizen"},
        ).json()
        assert result["filed"] is True
        assert result["reference_no"]
        assert _count_grievances(loaded_session) == 1

    def test_what_is_filed_matches_the_draft_shown(self, client, loaded_session):
        first = client.post(
            "/api/intake/message",
            json={"text": f"{ENGLISH} in Mukhed Town", "language": "en"},
        ).json()
        shown = first["draft"]
        result = client.post(
            f"/api/intake/{first['session_key']}/confirm", json={}
        ).json()

        filed = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == result["reference_no"])
        )
        assert filed.category_id == shown["category_id"]
        assert filed.taluka == shown["taluka"]
        assert filed.locality == shown["locality"]

    def test_a_draft_cannot_be_filed_twice(self, client, loaded_session):
        first = client.post(
            "/api/intake/message",
            json={"text": f"{ENGLISH} in Mukhed Town", "language": "en"},
        ).json()
        client.post(f"/api/intake/{first['session_key']}/confirm", json={})
        again = client.post(f"/api/intake/{first['session_key']}/confirm", json={})
        assert again.status_code == 409
        assert _count_grievances(loaded_session) == 1

    def test_unknown_session_is_a_404(self, client, loaded_session):
        assert (
            client.post("/api/intake/ses_nope/confirm", json={}).status_code == 404
        )

    def test_the_session_records_the_conversation(self, client, loaded_session):
        first = client.post(
            "/api/intake/message", json={"text": ENGLISH, "language": "en"}
        ).json()
        row = loaded_session.scalar(
            select(IntakeSession).where(
                IntakeSession.session_key == first["session_key"]
            )
        )
        roles = [turn["role"] for turn in row.transcript]
        assert roles == ["citizen", "system"]


class TestLanguages:
    def test_all_three_languages_are_offered(self, client, loaded_session):
        body = client.get("/api/intake/languages").json()
        codes = {entry["code"] for entry in body["languages"]}
        assert codes == {"mr", "hi", "en"}

    def test_capabilities_report_voice_honestly(self, client, loaded_session):
        """With no API key the UI must be told voice is unavailable."""
        body = client.get("/api/intake/languages").json()
        assert body["voice_available"] is False
        assert body["stt_model"] is None

    def test_marathi_offline_says_so_in_marathi(self, client, loaded_session):
        body = client.post(
            "/api/intake/message", json={"text": MARATHI, "language": "mr"}
        ).json()
        assert body["translation_available"] is False
        assert body["ready_to_confirm"] is False
        assert body["reply"] == intake_session.NO_TRANSLATION["mr"]

    def test_hindi_offline_says_so_in_hindi(self, client, loaded_session):
        body = client.post(
            "/api/intake/message", json={"text": HINDI, "language": "hi"}
        ).json()
        assert body["reply"] == intake_session.NO_TRANSLATION["hi"]

    def test_the_language_is_recorded_on_the_turn(self, client, loaded_session):
        body = client.post(
            "/api/intake/message", json={"text": MARATHI, "language": "mr"}
        ).json()
        assert body["transcript"][0]["language"] == "mr"

    def test_an_unsupported_language_falls_back_to_english(self, client, loaded_session):
        body = client.post(
            "/api/intake/message", json={"text": ENGLISH, "language": "fr"}
        ).json()
        assert body["language"] == "en"


class TestTranscription:
    def test_transcription_refuses_rather_than_inventing_text(
        self, client, loaded_session
    ):
        """A fabricated transcript would become a filed grievance."""
        response = client.post(
            "/api/intake/transcribe",
            files={"audio": ("speech.webm", b"not-really-audio", "audio/webm")},
            data={"language": "mr"},
        )
        assert response.status_code == 503
        assert "OPENAI_API_KEY" in response.json()["detail"]


class TestGeoExtraction:
    def test_place_names_come_from_the_loaded_data(self, loaded_session):
        talukas = geo.known_talukas(loaded_session)
        assert len(talukas) == 16
        assert "Mukhed" in talukas
        assert len(geo.known_localities(loaded_session)) == 51

    def test_a_locality_implies_its_taluka(self, loaded_session):
        found = geo.locate(loaded_session, "water is leaking in Mukhed Town")
        assert found["locality"] == "Mukhed Town"
        assert found["taluka"] == "Mukhed"

    def test_longest_match_wins(self, loaded_session):
        """"Mukhed Town" must not be reduced to "Mukhed"."""
        found = geo.locate(loaded_session, "the problem is at Mukhed Town")
        assert found["locality"] == "Mukhed Town"

    def test_text_with_no_known_place_yields_nothing(self, loaded_session):
        found = geo.locate(loaded_session, "there is a problem somewhere")
        assert found == {"taluka": None, "locality": None}


class TestTrackingAndDispute:
    def _file(self, client):
        first = client.post(
            "/api/intake/message",
            json={"text": f"{ENGLISH} in Mukhed Town", "language": "en"},
        ).json()
        return client.post(
            f"/api/intake/{first['session_key']}/confirm",
            json={"citizen_name": "Demo Citizen", "citizen_phone": "0000000000"},
        ).json()["reference_no"]

    def test_tracking_returns_the_case_and_its_timeline(self, client, loaded_session):
        reference = self._file(client)
        body = client.get(f"/api/track/{reference}").json()
        assert body["reference_no"] == reference
        assert body["timeline"]
        assert body["ai_summary"]["label"] == "AI-generated"

    def test_the_citizen_sees_their_own_details(self, client, loaded_session):
        reference = self._file(client)
        body = client.get(f"/api/track/{reference}").json()
        assert body["identity_masked"] is False
        assert body["citizen_name"] == "Demo Citizen"

    def test_unknown_reference_is_a_404(self, client, loaded_session):
        assert client.get("/api/track/GRV-NOPE").status_code == 404

    def test_a_dispute_reopens_the_case(self, client, loaded_session):
        reference = self._file(client)
        grievance = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == reference)
        )
        grievance.status = "Resolved"
        loaded_session.flush()

        result = client.post(
            f"/api/track/{reference}/feedback",
            json={"satisfied": False, "note": "The leak is still there."},
        ).json()
        assert result["reopened"] is True
        assert result["status"] == "In Progress"
        assert result["reopened_count"] == 1

    def test_a_dispute_is_audited_as_a_citizen_action(self, client, loaded_session):
        reference = self._file(client)
        client.post(
            f"/api/track/{reference}/feedback",
            json={"satisfied": False, "note": "Still broken."},
        )
        entry = loaded_session.scalar(
            select(AuditLog).where(
                AuditLog.target == reference,
                AuditLog.action == "REOPEN_ON_DISPUTE",
            )
        )
        assert entry is not None
        assert entry.actor == "CITIZEN"
        assert entry.rule_applied == "CITIZEN_DISPUTE_REOPENS_CASE"

    def test_confirming_a_resolution_does_not_reopen(self, client, loaded_session):
        reference = self._file(client)
        result = client.post(
            f"/api/track/{reference}/feedback",
            json={"satisfied": True, "note": "Fixed the next day, thank you."},
        ).json()
        assert result["reopened"] is False
        entry = loaded_session.scalar(
            select(AuditLog).where(
                AuditLog.target == reference,
                AuditLog.action == "CONFIRM_RESOLUTION",
            )
        )
        assert entry is not None
        assert entry.actor == "CITIZEN"


class TestConfirmedDraftSkipsIntake:
    def test_a_sensitive_draft_is_still_gated_on_confirmation(
        self, client, loaded_session
    ):
        """Confirming a draft must not bypass the policy gate."""
        sensitive = loaded_session.scalars(
            select(CategoryMaster).where(CategoryMaster.sensitive.is_(True))
        ).first()

        row = IntakeSession(
            session_key="ses_test_sensitive",
            language="en",
            transcript=[{"role": "citizen", "text": "A confidential concern."}],
            draft={
                "category_id": sensitive.category_id,
                "description": "A confidential concern.",
                "taluka": "Nanded",
                "confidence": 0.99,
            },
            missing_details=[],
        )
        loaded_session.add(row)
        loaded_session.flush()

        result = client.post(
            "/api/intake/ses_test_sensitive/confirm", json={}
        ).json()
        assert result["gate"]["rule_applied"] == "RULE_1_SENSITIVE_NEVER_AUTO_CLOSED"

        filed = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == result["reference_no"])
        )
        assert filed.status == "In Progress"
        assert filed.status != "Resolved"
