"""CLI.

  python -m radar run [--no-llm] [--no-email]     corrida diaria
  python -m radar probe "Grafana Labs" Kandji     ¿en qué ATS está esta empresa?
  python -m radar check-config                    ¿responde cada board de companies.yaml?
  python -m radar calibrate [--model ID]          set de 6 vacantes contra el scorer
  python -m radar discards [--days 7]             qué tiró el prefiltro y por qué
  python -m radar status <url|job_id> applied     tracker de postulaciones
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import pipeline, prefilter
from .db import DB
from .http import FetchError, Http
from .models import strip_accents
from .sources import ADAPTERS


def cmd_run(args) -> int:
    return pipeline.run(
        db_path=Path(args.db) if args.db else None,
        use_llm=not args.no_llm,
        send_email=not args.no_email,
    )


# --- probe -----------------------------------------------------------------

PROBES = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    # Aún sin adaptador (v2), pero vale la pena saber si la empresa está ahí.
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings",
}


def slug_variants(name: str) -> list[str]:
    base = strip_accents(name).lower().strip()
    base = re.sub(r"\b(inc|llc|ltd|corp|corporation|s\.?a\.?(?: de c\.?v\.?)?)\.?$", "", base).strip()
    words = re.findall(r"[a-z0-9]+", base)
    cands = ["".join(words), "-".join(words), "_".join(words)]
    if len(words) > 1:
        cands.append(words[0])
    if base.endswith((".io", ".ai", ".com", ".co")):
        cands.append("".join(re.findall(r"[a-z0-9]+", base.rsplit(".", 1)[0])))
    cands += [c + "hq" for c in cands[:1]] + [c + "inc" for c in cands[:1]]
    return list(dict.fromkeys(c for c in cands if c))


def _count(ats: str, data) -> int:
    if ats == "greenhouse":
        return len(data.get("jobs", []))
    if ats == "ashby":
        return len(data.get("jobs", []))
    if ats == "smartrecruiters":
        return int(data.get("totalFound", 0))
    return len(data)


def cmd_probe(args) -> int:
    http = Http()
    # Acepta "A, B, C" en un solo argumento (así lo pasa el workflow manual).
    names = [n.strip() for arg in args.names for n in arg.split(",") if n.strip()]
    for name in names:
        print(f"\n{name}")
        hits = 0
        for slug in slug_variants(name):
            for ats, url in PROBES.items():
                try:
                    data = http.get_json(url.format(slug=slug))
                except FetchError:
                    continue
                n = _count(ats, data)
                # SmartRecruiters responde 200 con 0 vacantes para cualquier slug: no cuenta.
                if ats == "smartrecruiters" and n == 0:
                    continue
                hits += 1
                note = "" if ats in ADAPTERS else "   (ATS aún sin adaptador)"
                print(f"  ✓ {ats:16} token: {slug:24} {n} vacantes{note}")
                if ats in ADAPTERS:
                    print(f"    - {{name: {name}, ats: {ats}, token: {slug}, tier: 2, verified: true}}")
        if not hits:
            print("  ✗ ninguna variante respondió. Abre su página de carreras y mira a dónde redirige.")
    return 0


def cmd_check_config(args) -> int:
    _, _, companies = pipeline.load_config()
    http = Http()
    bad = 0
    for c in companies:
        adapter = ADAPTERS.get(c.get("ats"))
        if adapter is None:
            print(f"✗ {c['name']:20} ATS '{c.get('ats')}' sin adaptador")
            bad += 1
            continue
        try:
            n = len(adapter.fetch(http, c))
        except Exception as e:  # noqa: BLE001
            print(f"✗ {c['name']:20} {c['ats']}/{c['token']}: {e}")
            bad += 1
            continue
        print(f"✓ {c['name']:20} {c['ats']}/{c['token']}: {n} vacantes")
    print(f"\n{len(companies) - bad}/{len(companies)} boards responden")
    return 1 if bad else 0


# --- calibrate -------------------------------------------------------------

URL_PATTERNS = [
    ("greenhouse", re.compile(r"greenhouse\.io/(?:v1/boards/)?([\w-]+)/jobs/(\d+)")),
    ("lever", re.compile(r"lever\.co/(?:v0/postings/)?([\w.-]+)/([0-9a-f-]{36})")),
]


def job_from_url(http: Http, url: str, company: str | None):
    for ats, pat in URL_PATTERNS:
        m = pat.search(url)
        if m:
            return ADAPTERS[ats].fetch_one(http, m.group(1), m.group(2), company)
    raise ValueError(f"URL no reconocida (solo Greenhouse/Lever): {url}")


def cmd_calibrate(args) -> int:
    from .models import Job
    from .scorer import Scorer, ScoringError

    settings, profile_yaml, _ = pipeline.load_config()
    scfg = settings["scorer"]
    pcfg = dict(settings["prefilter"], max_age_days=10_000)  # los casos pueden ser viejos
    cases = pipeline.load_yaml(pipeline.ROOT / "calibration" / "cases.yaml")
    model = args.model or scfg["model"]
    scorer = Scorer(profile_yaml, model, args.effort or scfg.get("effort", "low"),
                    scfg["max_description_chars"])
    threshold = scfg["min_score_for_digest"]
    http = Http()

    ok = total_cost = 0
    print(f"Modelo: {model} · umbral {threshold}\n")
    for case in cases:
        name, expect = case["name"], case["expect"]
        try:
            if case.get("url"):
                job = job_from_url(http, case["url"], case.get("company"))
            else:
                job = Job(source="manual", company=case["company"], job_id=name,
                          title=case["title"], location=case.get("location", ""),
                          url="", description=case["description"])
        except Exception as e:  # noqa: BLE001
            print(f"✗ {name}: no se pudo cargar ({e}). Reemplaza el caso en calibration/cases.yaml")
            continue

        # Se calibra el scorer, así que siempre puntúa; el prefiltro solo se reporta.
        reason = prefilter.check(job, pcfg)
        try:
            r = scorer.score(job.company, job.title, job.all_locations, job.url, job.description)
        except ScoringError as e:
            print(f"✗ {name}: error del scorer: {e}")
            continue
        total_cost += r.cost_usd
        s = r.score
        passed = (s["fit_score"] >= threshold) == (expect == "fit")
        got = f"{s['fit_score']} {s['verdict']} — {s['one_line']}"
        if reason:
            got += f"\n    prefiltro: {reason}"
            if expect == "fit":
                got += "  ← el prefiltro tiraría una vacante buena"
        ok += passed
        print(f"{'✓' if passed else '✗'} [{expect:6}] {name}\n    {got}")

    print(f"\n{ok}/{len(cases)} correctas · costo ${total_cost:.3f}")
    if ok != len(cases):
        print("La calibración NO pasa. Ajusta RULES en radar/scorer.py o el perfil y vuelve a correr.")
        return 1
    return 0


# --- discards / status -----------------------------------------------------

def cmd_discards(args) -> int:
    db = DB(args.db or pipeline.ROOT / "data" / "radar.db")
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    rows = db.discards_since(since)
    counts = Counter(pipeline.reason_bucket(r["discard_reason"]) for r in rows)
    print(f"{len(rows)} descartadas en {args.days} días\n")
    for reason, n in counts.most_common():
        print(f"{n:5} × {reason}")
    if args.verbose:
        print()
        for r in rows:
            print(f"- [{r['discard_reason']}] {r['company']} · {r['title']} · {r['location']}\n  {r['url']}")
    return 0


def cmd_status(args) -> int:
    db = DB(args.db or pipeline.ROOT / "data" / "radar.db")
    row = db.conn.execute(
        "SELECT source, company, job_id, title FROM jobs WHERE url = ? OR job_id = ?",
        (args.job, args.job),
    ).fetchone()
    if not row:
        print(f"No encontré la vacante {args.job}")
        return 1
    db.set_status(row["source"], row["company"], row["job_id"], args.status)
    print(f"{row['company']} · {row['title']} → {args.status}")
    db.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="radar")
    p.add_argument("--db", help="ruta alternativa al SQLite")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("--no-llm", action="store_true", help="solo fetch + prefiltro")
    r.add_argument("--no-email", action="store_true")
    r.set_defaults(fn=cmd_run)

    pr = sub.add_parser("probe")
    pr.add_argument("names", nargs="+")
    pr.set_defaults(fn=cmd_probe)

    cc = sub.add_parser("check-config")
    cc.set_defaults(fn=cmd_check_config)

    c = sub.add_parser("calibrate")
    c.add_argument("--model")
    c.add_argument("--effort", choices=["low", "medium", "high"])
    c.set_defaults(fn=cmd_calibrate)

    d = sub.add_parser("discards")
    d.add_argument("--days", type=int, default=7)
    d.add_argument("-v", "--verbose", action="store_true")
    d.set_defaults(fn=cmd_discards)

    s = sub.add_parser("status")
    s.add_argument("job", help="URL o job_id")
    s.add_argument("status", choices=["new", "applied", "interviewing", "rejected", "ignored"])
    s.set_defaults(fn=cmd_status)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
