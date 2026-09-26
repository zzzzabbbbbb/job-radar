"""Greenhouse Job Board API (pública, sin auth).

GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
"""
from __future__ import annotations

from ..http import FetchError, Http
from ..models import Job
from ._util import html_to_text, parse_iso

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def fetch(http: Http, company: dict) -> list[Job]:
    token = company["token"]
    data = http.get_json(API.format(token=token), params={"content": "true"})
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise FetchError(f"Greenhouse/{token}: respuesta sin lista 'jobs'")
    return [_to_job(company["name"], raw) for raw in data["jobs"]]


def fetch_one(http: Http, token: str, job_id: str, company_name: str | None = None) -> Job:
    raw = http.get_json(f"{API.format(token=token)}/{job_id}")
    return _to_job(company_name or token, raw)


def _to_job(company_name: str, raw: dict) -> Job:
    offices = [o.get("name") or "" for o in raw.get("offices") or []]
    location = (raw.get("location") or {}).get("name") or ""
    return Job(
        source="greenhouse",
        company=company_name,
        job_id=str(raw["id"]),
        title=(raw.get("title") or "").strip(),
        location=location,
        url=raw.get("absolute_url") or "",
        description=html_to_text(raw.get("content") or ""),
        # first_published es la fecha real de publicación; updated_at cambia con cualquier edición.
        posted_at=parse_iso(raw.get("first_published")) or parse_iso(raw.get("updated_at")),
        extra_locations=[o for o in offices if o and o.lower() not in location.lower()],
    )
