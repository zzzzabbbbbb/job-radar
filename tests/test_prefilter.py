from datetime import datetime, timedelta, timezone

import pytest

from radar import prefilter
from radar.models import Job, normalize_title


def job(title, location="Mexico City", description="", workplace="", posted_at=None, extra=None):
    return Job(source="greenhouse", company="X", job_id="1", title=title, location=location,
               url="", description=description, workplace=workplace, posted_at=posted_at,
               extra_locations=extra or [])


@pytest.fixture
def cfg(settings):
    return settings["prefilter"]


@pytest.mark.parametrize("title", [
    "IT Engineer", "IT Support Specialist", "Application Support Analyst",
    "Site Reliability Engineer", "SRE II", "Observability Engineer", "Automation Specialist",
    "Technical Support Engineer", "Customer Support Engineer", "Incident Manager",
    "Ingeniero de Soporte Técnico",
])
def test_titulos_de_interes_pasan(cfg, title):
    assert prefilter.check(job(title), cfg) is None


@pytest.mark.parametrize("title,bucket", [
    ("Account Executive", "disciplina"),
    ("Software Engineer, Backend", "disciplina"),
    ("Sales Engineer", "disciplina"),
    ("Product Designer", "disciplina"),
    ("Staff Site Reliability Engineer", "seniority"),
    ("Senior IT Engineer", "seniority"),
    ("Sr. Technical Support Engineer", "seniority"),
    ("Support Engineering Manager", "seniority"),
    ("IT Support Intern", "seniority"),
])
def test_titulos_fuera(cfg, title, bucket):
    assert prefilter.check(job(title), cfg).startswith(bucket)


def test_palabras_cortas_no_matchean_dentro_de_otras(cfg):
    # "sre" dentro de "ensure", "it" dentro de "with": no deben contar como disciplina.
    assert prefilter.check(job("Ensure Quality Coordinator"), cfg).startswith("disciplina")


@pytest.mark.parametrize("location,workplace,ok", [
    ("Mexico City, Mexico", "", True),
    ("Ciudad de México", "", True),
    ("CDMX (Hybrid)", "hybrid", True),
    ("Remote - Mexico", "", True),
    ("Remote - LATAM", "", True),
    ("Remote", "", True),
    ("Mexico", "", True),                    # ambiguo: decide el LLM
    ("Anywhere", "", True),
    ("Remote - US", "", False),
    ("Remote, Brazil", "", False),
    ("San Francisco, CA", "", False),
    ("Monterrey, Mexico", "onsite", False),
    ("London, UK", "hybrid", False),
])
def test_ubicacion(cfg, location, workplace, ok):
    r = prefilter.check(job("IT Engineer", location=location, workplace=workplace), cfg)
    assert (r is None) == ok, r


def test_ubicacion_en_el_titulo_o_en_otras_oficinas(cfg):
    assert prefilter.check(job("IT Engineer (Remote - Mexico)", location=""), cfg) is None
    assert prefilter.check(job("IT Engineer", location="Austin, TX", extra=["Mexico City"]), cfg) is None


@pytest.mark.parametrize("desc,years", [
    ("5+ years of experience in IT", 5),
    ("3-5 years of relevant experience", 3),
    ("Al menos 4 años de experiencia en soporte", 4),
    ("2+ years of experience with Okta; 7+ years of professional experience", 7),
    ("Founded 25 years ago. 3 years of experience required", 3),
    ("No experience requirement here", None),
])
def test_anios_requeridos(desc, years):
    assert prefilter.required_years(desc) == years


def test_descarta_por_anios_con_tolerancia(cfg):
    assert prefilter.check(job("IT Engineer", description="5+ years of experience"), cfg) is None
    r = prefilter.check(job("IT Engineer", description="6+ years of experience"), cfg)
    assert r.startswith("experiencia")


@pytest.mark.parametrize("desc,blocked", [
    ("Strong proficiency in Java", True),
    ("Expert-level Go programming", True),
    ("Deep experience with Ruby on Rails", True),
    ("Advanced C++ skills", True),
    ("Strong JavaScript skills", False),
    ("Familiarity with Java is a plus", False),
    ("We go above and beyond. Strong communication skills", False),
    ("Strong knowledge of C-level reporting", False),
])
def test_lenguajes_duros(cfg, desc, blocked):
    r = prefilter.check(job("Automation Engineer", location="Remote", description=desc), cfg)
    assert (r is not None and r.startswith("lenguaje")) == blocked, r


def test_blockers_duros(cfg):
    r = prefilter.check(job("IT Engineer", description="Active security clearance required."), cfg)
    assert r.startswith("blocker")


def test_antiguedad(cfg):
    cfg = dict(cfg, max_age_days=30)
    old = datetime.now(timezone.utc) - timedelta(days=40)
    assert prefilter.check(job("IT Engineer", posted_at=old), cfg).startswith("antigua")


def test_titulo_normalizado_para_dedup():
    assert normalize_title("IT Engineer (Remote - Mexico)") == "it engineer"
    assert normalize_title("IT Engineer - LATAM") == "it engineer"
    assert normalize_title("Ingeniero de Soporte Técnico") == "ingeniero de soporte tecnico"
