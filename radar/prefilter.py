"""Etapa 1: reglas deterministas y baratas. Devuelve None si pasa, o la razón del descarte.

Cada razón empieza con una categoría fija (disciplina:, seniority:, ubicacion:,
experiencia:, lenguaje:, blocker:, antigua:) para poder agrupar al calibrar.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from .models import Job, strip_accents


def _norm(text: str) -> str:
    return strip_accents(text or "").lower()


@lru_cache(maxsize=None)
def _term_re(term: str) -> re.Pattern:
    """Término como palabra completa ("sre" no matchea "ensure", "it" no matchea "with")."""
    t = re.escape(_norm(term))
    return re.compile(rf"(?<![a-z0-9]){t}(?![a-z0-9+#])")


def _find(terms: list[str], text: str) -> str | None:
    for term in terms:
        if _term_re(term).search(text):
            return term
    return None


YEARS_RE = re.compile(
    r"(\d{1,2})(?:\s*(?:-|–|to|a)\s*\d{1,2})?\s*\+?\s*(?:years?|yrs?|anos?)"
    r"(?:\s+\w+){0,6}?\s+(?:of\s+)?(?:experience|experiencia)",
)


def required_years(description: str) -> int | None:
    """El mayor mínimo de años pedido ("5+ years of experience", "3-5 años de experiencia")."""
    found = [int(m.group(1)) for m in YEARS_RE.finditer(_norm(description))]
    found = [y for y in found if 0 < y <= 15]  # "más de 20 años en el mercado" no es un requisito
    return max(found) if found else None


STRENGTH = r"(?:expert|expertise|advanced|strong|deep|extensive|proficien\w*|mastery|dominio|avanzado)"


def hard_language(description: str, languages: list[str]) -> str | None:
    """Lenguaje que el perfil no tiene, pedido a nivel fuerte/experto."""
    for lang in languages:
        if lang in {"Go", "C"}:
            # Demasiado ambiguos en minúsculas ("go live", "C-level"): se exige mayúscula
            # exacta y que no sea parte de C++/C#/Go-to.
            pat = rf"\b{lang}\b(?![+#\-/])"
            flags = 0
        else:
            pat = rf"(?<![a-z]){re.escape(lang.lower())}(?![a-z+#])"
            flags = re.IGNORECASE
        if lang.lower() == "java":
            pat = r"(?<![a-z])java(?!script|[a-z])"
            flags = re.IGNORECASE
        for m in re.finditer(pat, description, flags):
            window = description[max(0, m.start() - 80): m.start()]
            if re.search(STRENGTH, window, re.IGNORECASE):
                return lang
    return None


def location_reason(job: Job, cfg: dict) -> str | None:
    loc = _norm(job.all_locations)
    title = _norm(job.title)
    where = f"{loc} {title}"  # muchas empresas ponen "(Remote - Mexico)" en el título

    if _find(cfg["cdmx_words"], where):
        return None
    is_remote = job.workplace == "remote" or _find(cfg["remote_words"], where) is not None
    if not loc.strip() and not is_remote:
        return None  # sin datos: que decida el LLM
    if not is_remote:
        # "Mexico" a secas suele ser CDMX o remoto dentro de México: que decida el LLM.
        # Si nombra otra ciudad mexicana (Monterrey, Guadalajara...) es presencial fuera.
        if _find(["mexico", "mx"], loc) and not _find(cfg["other_mx_cities"], loc):
            return None
        return f"ubicacion: presencial/híbrido fuera de CDMX ({job.all_locations or '?'})"
    if _find(cfg["mexico_words"], where):
        return None
    foreign = _find(cfg["foreign_remote_words"], where)
    if foreign:
        return f"ubicacion: remoto restringido a otro país ({job.all_locations})"
    return None  # remoto sin restricción explícita


def check(job: Job, cfg: dict, now: datetime | None = None) -> str | None:
    now = now or datetime.now(timezone.utc)
    title = _norm(job.title)

    if job.posted_at and now - job.posted_at > timedelta(days=cfg["max_age_days"]):
        return f"antigua: publicada hace {(now - job.posted_at).days} días"

    excluded = _find(cfg["title_exclude"], title)
    if excluded:
        return f"disciplina: título contiene '{excluded}'"
    if not _find(cfg["title_include"], title):
        return "disciplina: título fuera de los roles de interés"

    if not _find(cfg.get("seniority_exempt", []), title):
        level = _find(cfg["seniority_exclude"], title)
        if level:
            return f"seniority: '{level}' en el título"
    if cfg.get("discard_senior", True) and _find(cfg["senior_words"], title):
        return "seniority: senior en el título"

    loc = location_reason(job, cfg)
    if loc:
        return loc

    desc = job.description
    ndesc = _norm(desc)
    blocker = _find(cfg["blocker_phrases"], ndesc)
    if blocker:
        return f"blocker: '{blocker}'"

    years = required_years(desc)
    limit = cfg["profile_years"] + cfg["years_tolerance"]
    if years is not None and years > limit:
        return f"experiencia: pide {years}+ años (límite {limit:g})"

    lang = hard_language(desc, cfg["hard_languages"])
    if lang:
        return f"lenguaje: pide {lang} a nivel fuerte/experto"

    return None
