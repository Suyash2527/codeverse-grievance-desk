"""Test fixtures.

The suite runs on in-memory SQLite so the hard-rule tests need no database
server and no network. Semantic retrieval needs Postgres and is exercised
separately in the RAG milestone; nothing in the policy layer depends on it.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, settings as real_settings
from app.loaders import reload_reference_data
from app.models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DATA_DIR = REPO_ROOT / "data"
SWAPPED_DATA_DIR = Path(__file__).resolve().parent / "fixtures" / "swapped_policy"


def _settings_for(data_dir: Path) -> Settings:
    """A Settings object pointing at a different data directory.

    Used to prove that behaviour follows the CSVs rather than the code.

    Built with dataclasses.replace rather than by listing every field, so
    adding a setting cannot break the test suite. Credentials are explicitly
    cleared: tests must never reach an external API.
    """
    return replace(
        real_settings,
        data_dir=data_dir,
        openai_api_key=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
        langfuse_host=None,
        n8n_webhook_base=None,
    )


@pytest.fixture
def real_settings_fixture() -> Settings:
    return _settings_for(REAL_DATA_DIR)


@pytest.fixture
def swapped_settings() -> Settings:
    return _settings_for(SWAPPED_DATA_DIR)


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture
def session(engine) -> Session:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as s:
        yield s


@pytest.fixture
def loaded_session(session: Session, real_settings_fixture: Settings) -> Session:
    """A session with the real supplied CSVs loaded."""
    reload_reference_data(session, real_settings_fixture)
    return session


@pytest.fixture
def client(engine, loaded_session):
    """TestClient wired to the in-memory database."""
    from fastapi.testclient import TestClient

    import app.main as main_module
    from app.db import get_session
    from app.main import app

    # The startup hook would create the schema on the configured DATABASE_URL;
    # the tests already have their own in-memory schema.
    main_module.init_db = lambda: None

    def override():
        yield loaded_session

    app.dependency_overrides[get_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
