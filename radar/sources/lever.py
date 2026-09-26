"""Lever Postings API (pública, sin auth).

GET https://api.lever.co/v0/postings/{company}?mode=json
"""
from __future__ import annotations

from ..http import FetchError, Http
from ..models import Job
from ._util import html_to_text, parse_epoch_ms

API = "https://api.lever.co/v0/postings/{token}"


def fetch(http: Http, company: dict) -> list[Job]:
    token = company["token"]
    data = http.get_json(API.format(token=token), params={"mode": "json"})
    if not isinstance(data, list):
        raise FetchError(f"Lever/{token}: se esperaba una lista de postings")
    return [_to_job(company["name"], raw) for raw in data]


def fetch_one(http: Http, token: str, job_id: str, company_name: str | None = None) -> Job:
    raw = http.get_json(f"{API.format(token=token)}/{job_id}", params={"mode": "json"})
    return _to_job(company_name or token, raw)


def _to_job(company_name: str, raw: dict) -> Job:
    cats = raw.get("categories") or {}
    location = cats.get("location") or ""
    all_locs = [loc for loc in cats.get("allLocations") or [] if loc and loc != location]

    parts = [raw.get("descriptionPlain") or html_to_text(raw.get("description") or "")]
    for block in raw.get("lists") or []:
        parts.append(f"{block.get('text', '')}\n{html_to_text(block.get('content') or '')}")
    parts.append(raw.get("additionalPlain") or html_to_text(raw.get("additional") or ""))

    workplace = (raw.get("workplaceType") or "").lower()
    return Job(
        source="lever",
        company=company_name,
        job_id=str(raw["id"]),
        title=(raw.get("text") or "").strip(),
        location=location,
        url=raw.get("hostedUrl") or "",
        description="\n\n".join(p.strip() for p in parts if p and p.strip()),
        posted_at=parse_epoch_ms(raw.get("createdAt")),
        workplace=workplace if workplace in {"remote", "hybrid", "onsite"} else "",
        extra_locations=all_locs,
    )
