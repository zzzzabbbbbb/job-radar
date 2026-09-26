"""Una corrida diaria: fetch → prefiltro → dedup → LLM → digest."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import digest, mailer, prefilter
from .db import DB, now_iso
from .digest import RunStats
from .http import Http
from .scorer import Scorer, ScoringError
from .sources import ADAPTERS

ROOT = Path(__file__).resolve().parent.parent
MAX_CONSECUTIVE_LLM_ERRORS = 3


def load_yaml(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config(root: Path = ROOT) -> tuple[dict, str, list[dict]]:
    settings = load_yaml(root / "config" / "settings.yaml")
    profile_yaml = (root / "config" / "profile.yaml").read_text(encoding="utf-8")
    companies = load_yaml(root / "config" / "companies.yaml") or []
    return settings, profile_yaml, companies


def reason_bucket(reason: str) -> str:
    """Agrupa razones para el resumen: sin la ubicación concreta entre paréntesis."""
    return re.sub(r"\s*\(.*\)$", "", reason)


def fetch_and_filter(db: DB, http: Http, companies: list[dict], cfg: dict, stats: RunStats) -> None:
    seen = now_iso()
    for company in companies:
        who = f"{company.get('name', '?')} ({company.get('ats', '?')})"
        adapter = ADAPTERS.get(company.get("ats"))
        if adapter is None:
            stats.failures.append((who, f"ATS '{company.get('ats')}' no soportado todavía"))
            continue
        try:
            jobs = adapter.fetch(http, company)
        except Exception as e:  # noqa: BLE001 — una fuente rota no tumba la corrida
            stats.failures.append((who, f"{type(e).__name__}: {e}"))
            db.record_source(stats.run_id, company["ats"], company["name"], False, error=str(e))
            continue

        db.record_source(stats.run_id, company["ats"], company["name"], True, n_jobs=len(jobs))
        stats.companies_ok += 1
        stats.fetched += len(jobs)
        open_ids: set[str] = set()
        for job in jobs:
            if job.job_id in open_ids:
                continue
            open_ids.add(job.job_id)
            if db.exists(job):
                db.touch(job, seen)
                continue
            stats.new += 1
            reason = prefilter.check(job, cfg)
            if reason:
                db.insert(job, seen, "discarded", reason)
                stats.discarded += 1
                stats.discard_reasons[reason_bucket(reason)] += 1
                continue
            dup = db.open_duplicate_of(job)
            if dup:
                db.insert(job, seen, "duplicate", f"duplicado de {dup['source']}:{dup['job_id']}")
                stats.duplicates += 1
                continue
            db.insert(job, seen, "pending")
            stats.passed += 1
        stats.closed += db.mark_closed(company["ats"], company["name"], open_ids, seen)
        db.conn.commit()

    if companies and stats.companies_ok == 0:
        stats.warnings.append("Ningún board respondió: hoy no hay datos, no es que no haya nada nuevo.")
    if stats.new >= 20 and stats.discarded / stats.new < 0.9:
        stats.warnings.append(
            f"El prefiltro solo descartó {stats.discarded / stats.new:.0%} de las nuevas "
            "(objetivo: más del 90%). Revisa las reglas en config/settings.yaml."
        )


def score_pending(db: DB, scorer: Scorer, scfg: dict, stats: RunStats) -> None:
    budget = scfg["monthly_budget_usd"]
    errors_in_a_row = 0
    for row in db.pending(scfg["max_scored_per_run"]):
        if stats.cost_month >= budget:
            stats.warnings.append(
                f"Se alcanzó el presupuesto mensual del LLM (${budget:.2f}); "
                "no se puntuó nada más este mes."
            )
            break
        try:
            result = scorer.score(row["company"], row["title"], row["location"], row["url"],
                                  row["description"])
        except ScoringError as e:
            stats.failures.append((f"Scorer · {row['company']} · {row['title']}", str(e)))
            errors_in_a_row += 1
            if errors_in_a_row >= MAX_CONSECUTIVE_LLM_ERRORS:
                stats.failures.append(("Scorer", "demasiados errores seguidos; se detuvo por hoy"))
                break
            continue
        errors_in_a_row = 0
        db.save_score(row, result.score, result.model, result.cost_usd)
        stats.scored += 1
        stats.cost_today += result.cost_usd
        stats.cost_month += result.cost_usd


def run(root: Path = ROOT, db_path: Path | None = None, use_llm: bool = True,
        send_email: bool = True, out_dir: Path | None = None,
        http: Http | None = None, scorer: Scorer | None = None) -> int:
    settings, profile_yaml, companies = load_config(root)
    scfg, dcfg, pcfg = settings["scorer"], settings["digest"], settings["prefilter"]
    db = DB(db_path or root / "data" / "radar.db")
    stats = RunStats()
    stats.run_id = db.start_run()
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    exit_code = 0
    try:
        fetch_and_filter(db, http or Http(), companies, pcfg, stats)

        stats.cost_month = db.month_cost(month_start)
        if use_llm:
            if scorer is None and not os.environ.get("ANTHROPIC_API_KEY"):
                stats.failures.append(("Scorer", "falta ANTHROPIC_API_KEY; no se puntuó nada"))
            else:
                scorer = scorer or Scorer(profile_yaml, scfg["model"], scfg.get("effort", "low"),
                                          scfg["max_description_chars"])
                score_pending(db, scorer, scfg, stats)
        stats.pending_left = db.count_pending()
        if stats.pending_left:
            stats.warnings.append(f"Quedan {stats.pending_left} vacantes por puntuar; siguen mañana.")

        to_notify = db.to_notify(scfg["min_score_for_digest"])
        if len(to_notify) > dcfg["warn_above"]:
            stats.warnings.append(
                f"{len(to_notify)} vacantes pasaron el umbral (máximo sano: {dcfg['warn_above']}). "
                f"Se muestran las {dcfg['max_items']} mejores; los umbrales necesitan ajuste."
            )
        closed = db.closed_of_interest()
        shown = to_notify[: dcfg["max_items"]]

        today = now.date()
        body = digest.render(today, shown, closed, stats, dcfg["max_items"])
        subject = digest.subject(today, len(shown), len(stats.failures))

        out_dir = out_dir or root / "digests"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{today.isoformat()}.md").write_text(body, encoding="utf-8")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write(body)
        print(body)

        if send_email:
            if mailer.smtp_configured():
                try:
                    mailer.send(subject, body)
                except Exception as e:  # noqa: BLE001
                    print(f"ERROR enviando correo: {e}")
                    exit_code = 1  # el workflow falla y GitHub te avisa: el correo no falla en silencio
            else:
                print("AVISO: SMTP no configurado; el digest solo quedó en digests/ y en el resumen del workflow.")

        # El digest quedó escrito (y commiteado por el workflow): no se repite mañana.
        stamp = now_iso()
        db.mark_notified(shown, stamp)
        db.mark_closed_notified(closed, stamp)
    finally:
        # Siempre se guarda el estado: lo ya puntuado costó dinero y no debe repetirse.
        db.finish_run(stats.run_id, stats.as_dict())
        db.close()
    return exit_code
