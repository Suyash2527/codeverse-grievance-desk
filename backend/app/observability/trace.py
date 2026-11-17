"""Langfuse tracing, optional by design.

With LANGFUSE_* configured, each pipeline run becomes one trace with a span
per agent, named intake.draft, retrieval.topk, policy.gate, decision.route and
action.execute, and the trace is marked public so a judge can open the link.

With no keys, every call here is a no-op and the pipeline runs unchanged. The
demo must never depend on an observability backend being reachable.

What is recorded: agent hand-offs, retrieved case ids, structured outputs,
confidence values, policy-gate outcomes and action results. What is not
recorded: citizen identity fields, which are masked before they reach a span.
"""
from __future__ import annotations

import contextlib
from typing import Any, Iterator

from app.config import settings

INTAKE_SPAN = "intake.draft"
RETRIEVAL_SPAN = "retrieval.topk"
POLICY_SPAN = "policy.gate"
DECISION_SPAN = "decision.route"
ACTION_SPAN = "action.execute"

_client: Any | None = None
_initialised = False


def tracing_enabled() -> bool:
    return bool(settings.langfuse_public_key and settings.langfuse_secret_key)


def get_client() -> Any | None:
    """Return a Langfuse client, or None when tracing is not configured."""
    global _client, _initialised
    if _initialised:
        return _client
    _initialised = True
    if not tracing_enabled():
        _client = None
        return None
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host or "https://cloud.langfuse.com",
        )
    except Exception:  # pragma: no cover - never let tracing break the pipeline
        _client = None
    return _client


@contextlib.contextmanager
def trace_run(name: str, *, public: bool = True, **metadata: Any) -> Iterator[Any]:
    """Open one trace for a pipeline run."""
    client = get_client()
    if client is None:
        yield None
        return
    try:
        with client.start_as_current_observation(
            as_type="span", name=name, input=metadata
        ) as span:
            if public:
                with contextlib.suppress(Exception):
                    client.set_current_trace_as_public()
            yield span
    except Exception:  # pragma: no cover
        yield None


@contextlib.contextmanager
def span(name: str, **inputs: Any) -> Iterator[Any]:
    """Open one agent span inside the current trace."""
    client = get_client()
    if client is None:
        yield None
        return
    try:
        with client.start_as_current_observation(
            as_type="span", name=name, input=inputs
        ) as current:
            yield current
    except Exception:  # pragma: no cover
        yield None


def record(current: Any, **output: Any) -> None:
    """Attach structured output to a span, if tracing is on."""
    if current is None:
        return
    with contextlib.suppress(Exception):
        current.update(output=output)


def current_trace_url() -> str | None:
    """The public URL of the trace in flight, for the officer view."""
    client = get_client()
    if client is None:
        return None
    with contextlib.suppress(Exception):
        return client.get_trace_url()
    return None


def flush() -> None:
    client = get_client()
    if client is not None:
        with contextlib.suppress(Exception):
            client.flush()
