from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Job:
    """Una vacante normalizada, venga del ATS que venga."""

    source: str          # greenhouse | lever
    company: str         # nombre legible de la empresa (config/companies.yaml)
    job_id: str          # id de la vacante dentro del ATS
    title: str
    location: str        # texto libre tal como lo publica el ATS
    url: str
    description: str     # texto plano
    posted_at: datetime | None = None
    workplace: str = ""  # remote | hybrid | onsite | "" (si el ATS lo dice)
    extra_locations: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source, self.company, self.job_id)

    @property
    def title_norm(self) -> str:
        return normalize_title(self.title)

    @property
    def all_locations(self) -> str:
        parts = [self.location, *self.extra_locations]
        return " | ".join(p for p in parts if p)


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def normalize_title(title: str) -> str:
    """Título normalizado para deduplicar la misma vacante publicada dos veces.

    Quita acentos, paréntesis (suelen traer la ubicación), guiones de ubicación
    al final y puntuación, para que "IT Engineer (Remote - Mexico)" e
    "IT Engineer - LATAM" colapsen a "it engineer".
    """
    t = strip_accents(title).lower()
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t)
    t = re.sub(r"\s[-–—|,]\s.*$", " ", t)
    t = re.sub(r"[^a-z0-9+#/ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()
