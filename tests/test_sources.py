from radar.sources import greenhouse, lever

from .conftest import FakeHttp, load_fixture


def test_greenhouse_parsea_y_limpia_html():
    http = FakeHttp({"boards/acme/jobs": load_fixture("greenhouse_acme.json")})
    jobs = greenhouse.fetch(http, {"name": "Acme", "token": "acme"})
    assert len(jobs) == 6
    j = jobs[0]
    assert (j.source, j.company, j.job_id) == ("greenhouse", "Acme", "1001")
    assert j.location == "Mexico City, Mexico"
    assert "2+ years of experience" in j.description
    assert "<" not in j.description and "&lt;" not in j.description
    assert "- Kandji" in j.description
    assert j.posted_at is not None


def test_lever_junta_listas_y_workplace():
    http = FakeHttp({"postings/globex": load_fixture("lever_globex.json")})
    jobs = lever.fetch(http, {"name": "Globex", "token": "globex"})
    assert len(jobs) == 2
    j = jobs[0]
    assert j.workplace == "remote"
    assert j.extra_locations == ["Colombia"]
    assert "3+ years of experience in technical support" in j.description
    assert "Remote within Mexico." in j.description
    assert j.posted_at.year == 2026
