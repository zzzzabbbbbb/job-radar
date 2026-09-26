"""Estado en SQLite: un archivo, commiteado al repo después de cada corrida."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    source          TEXT NOT NULL,
    company         TEXT NOT NULL,
    job_id          TEXT NOT NULL,
    title           TEXT NOT NULL,
    title_norm      TEXT NOT NULL,
    location        TEXT,
    url             TEXT,
    posted_at       TEXT,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    closed_at       TEXT,
    -- pending: pasó el prefiltro y espera al LLM; discarded: lo tiró el prefiltro;
    -- duplicate: misma empresa + título que otra abierta; scored: ya puntuada.
    stage           TEXT NOT NULL,
    discard_reason  TEXT,
    description     TEXT,           -- solo se guarda para las que pasan el prefiltro
    fit_score       INTEGER,
    verdict         TEXT,
    score_json      TEXT,
    scored_model    TEXT,
    scored_at       TEXT,
    cost_usd        REAL,
    notified_at     TEXT,
    closed_notified_at TEXT,
    -- Lo actualizas tú: new, applied, interviewing, rejected, ignored.
    status          TEXT NOT NULL DEFAULT 'new',
    PRIMARY KEY (source, company, job_id)
);
CREATE INDEX IF NOT EXISTS jobs_dedup ON jobs (company, title_norm);
CREATE INDEX IF NOT EXISTS jobs_stage ON jobs (stage);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    stats_json  TEXT
);

CREATE TABLE IF NOT EXISTS source_status (
    run_id   INTEGER NOT NULL,
    source   TEXT NOT NULL,
    company  TEXT NOT NULL,
    ok       INTEGER NOT NULL,
    n_jobs   INTEGER,
    error    TEXT
);
"""

ALLOWED_STATUS = {"new", "applied", "interviewing", "rejected", "ignored"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class DB:
    """SQLite en disco, pero lo que vive en git es `radar.sql`: un dump de texto.

    Un binario commiteado a diario guarda el archivo entero en cada commit; el dump
    son líneas INSERT que git comprime como diffs. Al abrir, si el .db no existe
    (checkout limpio en Actions), se reconstruye desde el dump; al cerrar, se reescribe.
    """

    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.dump_path = path.with_suffix(".sql")
        fresh = not path.exists()
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        if fresh and self.dump_path.exists():
            self.conn.executescript(self.dump_path.read_text(encoding="utf-8"))
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.commit()
        self.dump_path.write_text("\n".join(self.conn.iterdump()) + "\n", encoding="utf-8")
        self.conn.close()

    # --- corridas ---------------------------------------------------------

    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (now_iso(),))
        return cur.lastrowid

    def finish_run(self, run_id: int, stats: dict) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, stats_json = ? WHERE id = ?",
            (now_iso(), json.dumps(stats, ensure_ascii=False), run_id),
        )
        self.conn.commit()

    def record_source(self, run_id: int, source: str, company: str, ok: bool,
                      n_jobs: int | None = None, error: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO source_status VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, source, company, int(ok), n_jobs, error),
        )

    # --- vacantes ---------------------------------------------------------

    def exists(self, job: Job) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM jobs WHERE source = ? AND company = ? AND job_id = ?", job.key
        ).fetchone() is not None

    def touch(self, job: Job, seen: str) -> None:
        """Ya la conocíamos: solo actualiza last_seen (y la reabre si había desaparecido)."""
        self.conn.execute(
            "UPDATE jobs SET last_seen = ?, closed_at = NULL, closed_notified_at = NULL "
            "WHERE source = ? AND company = ? AND job_id = ?",
            (seen, *job.key),
        )

    def open_duplicate_of(self, job: Job) -> sqlite3.Row | None:
        """Otra vacante abierta de la misma empresa con el mismo título normalizado."""
        return self.conn.execute(
            "SELECT * FROM jobs WHERE company = ? AND title_norm = ? AND closed_at IS NULL "
            "AND NOT (source = ? AND job_id = ?) AND stage != 'discarded' LIMIT 1",
            (job.company, job.title_norm, job.source, job.job_id),
        ).fetchone()

    def insert(self, job: Job, seen: str, stage: str, reason: str | None = None) -> None:
        keep_desc = stage == "pending"
        self.conn.execute(
            "INSERT INTO jobs (source, company, job_id, title, title_norm, location, url, "
            "posted_at, first_seen, last_seen, stage, discard_reason, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                *job.key, job.title, job.title_norm, job.all_locations, job.url,
                job.posted_at.isoformat() if job.posted_at else None,
                seen, seen, stage, reason, job.description if keep_desc else None,
            ),
        )

    def mark_closed(self, source: str, company: str, open_ids: set[str], when: str) -> int:
        """Lo que estaba abierto en este board y ya no aparece se marca cerrado.

        Solo se llama cuando el fetch de ese board salió bien: una falla nunca cierra nada.
        """
        rows = self.conn.execute(
            "SELECT job_id FROM jobs WHERE source = ? AND company = ? AND closed_at IS NULL",
            (source, company),
        ).fetchall()
        gone = [r["job_id"] for r in rows if r["job_id"] not in open_ids]
        self.conn.executemany(
            "UPDATE jobs SET closed_at = ? WHERE source = ? AND company = ? AND job_id = ?",
            [(when, source, company, jid) for jid in gone],
        )
        return len(gone)

    def pending(self, limit: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM jobs WHERE stage = 'pending' AND closed_at IS NULL "
            "ORDER BY first_seen, company LIMIT ?",
            (limit,),
        ).fetchall()

    def count_pending(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE stage = 'pending' AND closed_at IS NULL"
        ).fetchone()[0]

    def save_score(self, row: sqlite3.Row, score: dict, model: str, cost: float) -> None:
        self.conn.execute(
            "UPDATE jobs SET stage = 'scored', fit_score = ?, verdict = ?, score_json = ?, "
            "scored_model = ?, scored_at = ?, cost_usd = ? "
            "WHERE source = ? AND company = ? AND job_id = ?",
            (score["fit_score"], score["verdict"], json.dumps(score, ensure_ascii=False),
             model, now_iso(), cost, row["source"], row["company"], row["job_id"]),
        )
        self.conn.commit()  # cada puntuación cuesta dinero: no perderla si algo truena después

    def to_notify(self, min_score: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM jobs WHERE stage = 'scored' AND notified_at IS NULL "
            "AND closed_at IS NULL AND fit_score >= ? AND verdict != 'skip' "
            "ORDER BY fit_score DESC, first_seen",
            (min_score,),
        ).fetchall()

    def mark_notified(self, rows: list[sqlite3.Row], when: str) -> None:
        self.conn.executemany(
            "UPDATE jobs SET notified_at = ? WHERE source = ? AND company = ? AND job_id = ?",
            [(when, r["source"], r["company"], r["job_id"]) for r in rows],
        )

    def closed_of_interest(self) -> list[sqlite3.Row]:
        """Cerradas desde la última vez que avisamos, que te importaban:
        las que salieron en un digest o las que marcaste como applied/interviewing."""
        return self.conn.execute(
            "SELECT * FROM jobs WHERE closed_at IS NOT NULL AND closed_notified_at IS NULL "
            "AND (notified_at IS NOT NULL OR status IN ('applied', 'interviewing')) "
            "ORDER BY closed_at DESC"
        ).fetchall()

    def mark_closed_notified(self, rows: list[sqlite3.Row], when: str) -> None:
        self.conn.executemany(
            "UPDATE jobs SET closed_notified_at = ? WHERE source = ? AND company = ? AND job_id = ?",
            [(when, r["source"], r["company"], r["job_id"]) for r in rows],
        )

    def month_cost(self, month_start: str) -> float:
        """Costo del LLM desde `month_start` (ISO, primer día del mes)."""
        row = self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM jobs WHERE scored_at >= ?",
            (month_start,),
        ).fetchone()
        return float(row[0])

    def discards_since(self, since: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT company, title, location, url, discard_reason FROM jobs "
            "WHERE stage = 'discarded' AND first_seen >= ? ORDER BY discard_reason, company",
            (since,),
        ).fetchall()

    def set_status(self, source: str, company: str, job_id: str, status: str) -> bool:
        if status not in ALLOWED_STATUS:
            raise ValueError(f"status debe ser uno de {sorted(ALLOWED_STATUS)}")
        cur = self.conn.execute(
            "UPDATE jobs SET status = ? WHERE source = ? AND company = ? AND job_id = ?",
            (status, source, company, job_id),
        )
        self.conn.commit()
        return cur.rowcount > 0
