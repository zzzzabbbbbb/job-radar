"""Adaptadores de ATS. Cada uno recibe la entrada de companies.yaml y devuelve Jobs.

Agregar un ATS nuevo = un módulo con `fetch(http, company) -> list[Job]`
y `fetch_one(http, board, job_id) -> Job` y registrarlo en ADAPTERS.
"""
from __future__ import annotations

from . import greenhouse, lever

ADAPTERS = {
    "greenhouse": greenhouse,
    "lever": lever,
}

