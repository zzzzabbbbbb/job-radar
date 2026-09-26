"""Digest diario en markdown."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

VERDICT_LABEL = {
    "apply_now": "aplica ya",
    "worth_considering": "vale la pena",
    "stretch": "stretch",
    "skip": "skip",
}


@dataclass
class RunStats:
    run_id: int = 0
    companies_ok: int = 0
    fetched: int = 0
    new: int = 0
    discarded: int = 0
    duplicates: int = 0
    passed: int = 0
    scored: int = 0
    closed: int = 0
    pending_left: int = 0
    cost_today: float = 0.0
    cost_month: float = 0.0
    failures: list[tuple[str, str]] = field(default_factory=list)  # (quién, error)
    discard_reasons: Counter = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["discard_reasons"] = dict(self.discard_reasons)
        return d


def _age(posted_at: str | None) -> str:
    if not posted_at:
        return ""
    try:
        days = (datetime.now(timezone.utc) - datetime.fromisoformat(posted_at)).days
    except ValueError:
        return ""
    return "publicada hoy" if days <= 0 else f"publicada hace {days} d"


def render(today: date, jobs: list, closed: list, stats: RunStats, max_items: int) -> str:
    out: list[str] = [f"# Job Radar · {today.isoformat()}", ""]

    n = len(jobs)
    head = f"**{n} vacante{'s' if n != 1 else ''} para revisar**" if n else "**Nada nuevo que valga la pena hoy.**"
    out.append(
        f"{head} · {stats.new} nuevas de {stats.fetched} vistas en {stats.companies_ok} boards · "
        f"{stats.discarded} descartadas por reglas · {stats.scored} puntuadas por el LLM · "
        f"costo hoy ${stats.cost_today:.2f} (mes ${stats.cost_month:.2f})"
    )
    out.append("")

    if stats.warnings:
        out.append("## ⚠️ Avisos")
        out += [f"- {w}" for w in stats.warnings]
        out.append("")

    for i, row in enumerate(jobs[:max_items], 1):
        s = json.loads(row["score_json"])
        meta = " · ".join(p for p in [row["location"], _age(row["posted_at"])] if p)
        out.append(f"## {i}. [{row['title']}]({row['url']})")
        out.append(f"**{row['company']}** · score **{s['fit_score']}** · {VERDICT_LABEL[s['verdict']]}"
                   f" · seniority {s['seniority_read']}")
        if meta:
            out[-1] += "  "  # salto de línea en markdown
            out.append(meta)
        out.append("")
        out.append(f"> {s['one_line']}")
        out.append("")
        for m in s["matches"][:5]:
            out.append(f"- ✅ {m}")
        for g in s["gaps"][:4]:
            out.append(f"- ⚠️ {g}")
        out.append("")

    if closed:
        out.append("## Cerradas desde el último digest")
        for row in closed:
            tag = f" ({row['status']})" if row["status"] in ("applied", "interviewing") else ""
            out.append(f"- {row['company']} · {row['title']}{tag} · abierta desde {row['first_seen'][:10]}")
        out.append("")

    if stats.failures:
        out.append("## ❌ Fuentes con falla")
        out += [f"- **{who}**: {err[:200]}" for who, err in stats.failures]
        out.append("")

    if stats.discard_reasons:
        out.append("## Descartes de hoy por razón")
        for reason, count in stats.discard_reasons.most_common():
            out.append(f"- {count} × {reason}")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def subject(today: date, n_jobs: int, n_failures: int) -> str:
    s = f"Job Radar {today.isoformat()}: {n_jobs} vacante{'s' if n_jobs != 1 else ''}"
    if n_failures:
        s += f" · {n_failures} fuente{'s' if n_failures != 1 else ''} con falla"
    return s
