"""Etapa 2: el LLM puntúa solo lo que sobrevivió al prefiltro."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import anthropic
from pydantic import BaseModel

# USD por millón de tokens: (input, output, cache write 5 min, cache read).
PRICING = {
    "claude-opus-5": (5.00, 25.00, 6.25, 0.50),
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
}
# Modelos donde se activa el fallback del servidor ante un rechazo por política.
FALLBACK_MODELS = {"claude-opus-5"}
# Modelos que rechazan el parámetro effort.
NO_EFFORT_MODELS = {"claude-haiku-4-5"}

RULES = """\
Eres el filtro de vacantes de un candidato real. Tu trabajo es decir que no a casi todo:
lo que apruebes le llega por correo, y si le mandas vacantes que no le aplican va a dejar
de leer el correo. Un falso negativo cuesta menos que un falso positivo.

Reglas (obligatorias):
- Sé escéptico, no generoso. La mayoría de las vacantes no encajan.
- Si hay un blocker duro del perfil, el score es menor a 30 aunque todo lo demás se vea bien.
- No infieras habilidades que el perfil no declara. Administrar Okta no es configurar SAML.
- La sección de límites del perfil pesa tanto como la de fortalezas.
- Un rol que pide el doble de años de los que tengo es un skip, no un stretch.
- Ante la duda, skip.

Cómo llenar la respuesta:
- fit_score: 0 a 100. 65 o más significa "vale la pena que lo lea hoy".
  80+ solo si casi todos los requisitos duros están cubiertos por fortalezas declaradas.
- verdict: apply_now (encaja claramente), worth_considering (encaja con huecos menores),
  stretch (alcanzable pero con huecos reales), skip (no).
- matches: requisitos de la vacante cubiertos por fortalezas DECLARADAS en el perfil.
- gaps: requisitos que el perfil no cubre o que chocan con honest_limits.
- blockers: solo hard_blockers del perfil que la vacante activa (años, lenguaje experto,
  clearance, presencial fuera de CDMX o reubicación, título de CS obligatorio). Vacío si no hay.
- seniority_read: below | at_level | above, respecto a 3.5 años de IT/soporte.
- one_line: una frase en español que explique el veredicto, directa, sin adornos.

Ubicación: remoto (incluido remoto LatAm/México/Américas), híbrido en CDMX o presencial en
CDMX están bien. Remoto restringido a otro país, o presencial/híbrido fuera de CDMX, es blocker.
Si la vacante no dice nada de ubicación compatible, trátalo como gap, no como blocker.

El perfil del candidato:
"""


class Score(BaseModel):
    fit_score: int
    verdict: Literal["apply_now", "worth_considering", "stretch", "skip"]
    matches: list[str]
    gaps: list[str]
    blockers: list[str]
    seniority_read: Literal["below", "at_level", "above"]
    one_line: str


class ScoringError(Exception):
    pass


@dataclass
class ScoreResult:
    score: dict
    cost_usd: float
    model: str


def enforce_guardrails(score: dict) -> dict:
    """Reglas que no dejamos a criterio del modelo."""
    s = dict(score)
    s["fit_score"] = max(0, min(100, int(s["fit_score"])))
    if s["blockers"]:
        s["fit_score"] = min(s["fit_score"], 29)
        s["verdict"] = "skip"
    if s["verdict"] == "skip":
        s["fit_score"] = min(s["fit_score"], 64)
    return s


def cost_of(usage, model: str) -> float:
    p_in, p_out, p_write, p_read = PRICING.get(model, PRICING["claude-opus-5"])
    return (
        (usage.input_tokens or 0) * p_in
        + (usage.output_tokens or 0) * p_out
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * p_write
        + (getattr(usage, "cache_read_input_tokens", 0) or 0) * p_read
    ) / 1_000_000


class Scorer:
    def __init__(self, profile_yaml: str, model: str, effort: str = "low",
                 max_description_chars: int = 15000, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.max_chars = max_description_chars
        # Prefijo estable (reglas + perfil) → se cachea entre vacantes de la misma corrida.
        self.system = [{
            "type": "text",
            "text": RULES + profile_yaml,
            "cache_control": {"type": "ephemeral"},
        }]

    def _job_message(self, company: str, title: str, location: str, url: str,
                     description: str) -> str:
        desc = description or "(sin descripción)"
        if len(desc) > self.max_chars:
            desc = desc[: self.max_chars] + "\n[... descripción recortada ...]"
        return (
            f"Empresa: {company}\nPuesto: {title}\nUbicación: {location or '(no indicada)'}\n"
            f"URL: {url}\n\nDescripción:\n{desc}"
        )

    def score(self, company: str, title: str, location: str, url: str,
              description: str) -> ScoreResult:
        kwargs = dict(
            model=self.model,
            max_tokens=4000,
            system=self.system,
            messages=[{"role": "user", "content": self._job_message(
                company, title, location, url, description)}],
            output_format=Score,
        )
        if self.model not in NO_EFFORT_MODELS:
            kwargs["output_config"] = {"effort": self.effort}
        try:
            if self.model in FALLBACK_MODELS:
                resp = self.client.beta.messages.parse(
                    **kwargs,
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            else:
                resp = self.client.messages.parse(**kwargs)
        except anthropic.APIError as e:
            raise ScoringError(f"{type(e).__name__}: {e}") from e

        cost = cost_of(resp.usage, resp.model or self.model)
        if resp.stop_reason == "refusal":
            raise ScoringError("el modelo rechazó la solicitud (refusal)")
        if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
            raise ScoringError(f"respuesta incompleta (stop_reason={resp.stop_reason})")
        return ScoreResult(
            score=enforce_guardrails(resp.parsed_output.model_dump()),
            cost_usd=cost,
            model=resp.model or self.model,
        )
