from unittest.mock import Mock

import pytest

from app.web_search import service
from app.web_search.policy import SearchPolicy
from app.web_search.tavily import WebSearchError


def test_cached_search_persists_course_source_without_provider_call(monkeypatch) -> None:
    db = Mock()
    db.scalar.return_value = None
    provider = Mock(side_effect=AssertionError("cache hit must not call provider"))
    monkeypatch.setattr(service, "cached_search", lambda *_a, **_k: [{
        "title": "Reference", "url": "https://example.org/reference",
        "site_name": "example.org", "snippet": "Excerpt",
    }])
    monkeypatch.setattr(service, "search", provider)

    results = service.search_with_sources(
        db, course_id="course-1", query="question", policy=SearchPolicy(),
    )

    assert results[0]["url"] == "https://example.org/reference"
    assert db.add.call_args.args[0].course_id == "course-1"
    db.flush.assert_called_once()
    provider.assert_not_called()


def test_provider_failure_records_failed_audit(monkeypatch) -> None:
    db = Mock()
    audit = object()
    monkeypatch.setattr(service, "cached_search", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "begin_call", lambda *_a, **_k: (audit, 0))
    monkeypatch.setattr(service, "record_search", lambda: None)
    monkeypatch.setattr(service, "search", Mock(side_effect=WebSearchError("failed")))
    finish = Mock()
    monkeypatch.setattr(service, "finish_call", finish)
    monkeypatch.setattr(service, "provider_status_from_error", lambda _exc: "failed")

    with pytest.raises(WebSearchError):
        service.search_with_sources(
            db, course_id="course-1", query="question", policy=SearchPolicy(),
        )

    assert finish.call_args.kwargs["status"] == "failed"


@pytest.mark.parametrize(
    ("policy", "configured", "expected"),
    [
        (SearchPolicy(allow=False), True, "disabled_by_request"),
        (SearchPolicy(daily_limit=0), True, "daily_limit"),
        (SearchPolicy(), False, "unconfigured"),
        (SearchPolicy(), True, "allowed"),
    ],
)
def test_shared_availability_reports_policy_and_configuration(monkeypatch, policy, configured, expected) -> None:
    monkeypatch.setattr(service, "configured", lambda: configured)
    available, reason = service.availability(policy)
    assert (available, reason) == (expected == "allowed", expected)


def test_daily_limit_audit_requires_configured_provider(monkeypatch) -> None:
    begin = Mock()
    monkeypatch.setattr(service, "configured", lambda: False)
    monkeypatch.setattr(service, "begin_call", begin)
    service.record_daily_limit(Mock(), course_id="course-1", reason="daily_limit")
    begin.assert_not_called()
