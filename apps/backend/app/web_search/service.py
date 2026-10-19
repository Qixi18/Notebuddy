"""Shared web-search execution; callers own query construction and answer policy."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import WebSource
from app.services.provider_audit import begin_call, finish_call, provider_status_from_error
from app.web_search.policy import (
    SearchPolicy,
    cache_search,
    cached_search,
    can_search,
    record_search,
)
from app.web_search.source_review import review_results
from app.web_search.tavily import WebSearchError, configured, search


def search_policy(*, allow: bool) -> SearchPolicy:
    return SearchPolicy(
        allow=allow, max_results=4, daily_limit=30,
        timeout_seconds=settings.web_search_timeout_seconds,
    )


def search_with_sources(
    db: Session,
    *,
    course_id: str,
    query: str,
    policy: SearchPolicy,
    material_id: str | None = None,
    source_query: str | None = None,
    origin: str | None = None,
) -> list[dict]:
    """Use cache, audit provider calls, and persist reviewed course-scoped sources.

    Callers check policy and availability before invoking this function.
    """
    audit = None
    started = None
    try:
        results = cached_search(query, max_age_seconds=policy.cache_seconds)
        if results is None:
            metadata = {"query_length": len(query)}
            if origin:
                metadata["origin"] = origin
            else:
                metadata["max_results"] = policy.max_results
            audit, started = begin_call(
                db, provider="tavily", operation="search", course_id=course_id,
                model="tavily-basic", request_units=1, metadata=metadata,
            )
            record_search()
            results = review_results(list(search(query, max_results=policy.max_results)))["results"]
            cache_search(query, results)
            finish_call(db, audit, started, status="success", response_units=len(results))
        for item in results:
            if db.scalar(select(WebSource.id).where(
                WebSource.course_id == course_id, WebSource.url == item["url"],
            )) is None:
                db.add(WebSource(
                    course_id=course_id, material_id=material_id,
                    search_query=(source_query or query)[:1000],
                    title=item["title"], url=item["url"], site_name=item["site_name"],
                    snippet=item["snippet"], score=item.get("score"),
                    published_at=item.get("published_at"),
                ))
        db.flush()
        return results
    except WebSearchError as exc:
        if audit is not None:
            finish_call(
                db, audit, started, status=provider_status_from_error(exc),
                error_type=type(exc).__name__,
            )
        raise


def availability(policy: SearchPolicy) -> tuple[bool, str]:
    allowed, reason = can_search(policy)
    if not allowed:
        return False, reason
    return (True, reason) if configured() else (False, "unconfigured")


def record_daily_limit(db: Session, *, course_id: str, reason: str) -> None:
    audit, started = begin_call(
        db, provider="tavily", operation="search", course_id=course_id,
        model="tavily-basic", request_units=0, metadata={"reason": reason},
    )
    finish_call(db, audit, started, status="rate_limited")
