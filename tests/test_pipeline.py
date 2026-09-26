import sqlite3

from radar import pipeline
from radar.http import FetchError
from radar.scorer import ScoreResult

from .conftest import FakeHttp, load_fixture


class FakeScorer:
    def __init__(self):
        self.calls = []

    def score(self, company, title, location, url, description):
        self.calls.append(title)
        good = "Customer Support" in title or "IT Support" in title
        s = {"fit_score": 82 if good else 40, "verdict": "apply_now" if good else "skip",
             "matches": ["Okta"], "gaps": [], "blockers": [], "seniority_read": "at_level",
             "one_line": "Encaja." if good else "No encaja."}
        return ScoreResult(score=s, cost_usd=0.01, model="fake")


def routes(gh=None, lv=None):
    return {
        "boards/acme/jobs": gh or load_fixture("greenhouse_acme.json"),
        "postings/globex": lv or load_fixture("lever_globex.json"),
        "boards/rota/jobs": FetchError("HTTP 500 en rota"),
    }


def rows(root):
    conn = sqlite3.connect(root / "data" / "radar.db")
    conn.row_factory = sqlite3.Row
    return {r["job_id"]: r for r in conn.execute("SELECT * FROM jobs")}


def run(root, http, scorer):
    return pipeline.run(root=root, http=http, scorer=scorer, send_email=False)


def test_corrida_completa(tmp_root):
    scorer = FakeScorer()
    assert run(tmp_root, FakeHttp(routes()), scorer) == 0
    jobs = rows(tmp_root)

    # Todo queda en la base, lo descartado con su razón.
    assert len(jobs) == 8
    assert jobs["1002"]["stage"] == "discarded" and "seniority" in jobs["1002"]["discard_reason"]
    assert jobs["1004"]["discard_reason"].startswith("ubicacion")
    assert jobs["1005"]["discard_reason"].startswith("experiencia")
    assert jobs["1006"]["discard_reason"].startswith("lenguaje")
    # Solo lo que sobrevivió llega al LLM.
    assert sorted(scorer.calls) == ["Customer Support Engineer (Remote - Mexico)", "IT Support Engineer"]

    digest = (tmp_root / "digests").glob("*.md").__next__().read_text()
    assert "IT Support Engineer" in digest and "Customer Support Engineer" in digest
    # Las fallas se reportan, no tumban la corrida.
    assert "Rota (greenhouse)" in digest and "HTTP 500" in digest
    assert "workday" in digest


def test_no_repite_ni_vuelve_a_puntuar(tmp_root):
    run(tmp_root, FakeHttp(routes()), FakeScorer())
    scorer = FakeScorer()
    run(tmp_root, FakeHttp(routes()), scorer)
    assert scorer.calls == []
    digests = sorted((tmp_root / "digests").glob("*.md"))
    assert "Nada nuevo" in digests[-1].read_text()


def test_detecta_cerradas_que_importaban(tmp_root):
    run(tmp_root, FakeHttp(routes()), FakeScorer())
    gh = load_fixture("greenhouse_acme.json")
    gh["jobs"] = [j for j in gh["jobs"] if j["id"] != 1001]  # la que salió en el digest
    run(tmp_root, FakeHttp(routes(gh=gh)), FakeScorer())
    jobs = rows(tmp_root)
    assert jobs["1001"]["closed_at"] is not None
    assert "Cerradas desde el último digest" in sorted((tmp_root / "digests").glob("*.md"))[-1].read_text()


def test_una_falla_no_cierra_vacantes(tmp_root):
    run(tmp_root, FakeHttp(routes()), FakeScorer())
    broken = routes()
    broken["boards/acme/jobs"] = FetchError("timeout")
    run(tmp_root, FakeHttp(broken), FakeScorer())
    assert all(r["closed_at"] is None for r in rows(tmp_root).values())


def test_dedup_por_titulo_normalizado(tmp_root):
    gh = load_fixture("greenhouse_acme.json")
    clone = dict(gh["jobs"][0], id=2001, title="IT Support Engineer - LATAM",
                 absolute_url="https://job-boards.greenhouse.io/acme/jobs/2001")
    gh["jobs"].append(clone)
    scorer = FakeScorer()
    run(tmp_root, FakeHttp(routes(gh=gh)), scorer)
    assert scorer.calls.count("IT Support Engineer") == 1
    assert rows(tmp_root)["2001"]["stage"] == "duplicate"


def test_presupuesto_mensual_detiene_el_scorer(tmp_root, settings):
    import yaml
    settings["scorer"]["monthly_budget_usd"] = 0.005
    (tmp_root / "config" / "settings.yaml").write_text(yaml.safe_dump(settings))
    scorer = FakeScorer()
    run(tmp_root, FakeHttp(routes()), scorer)
    assert len(scorer.calls) == 1
    digest = next((tmp_root / "digests").glob("*.md")).read_text()
    assert "presupuesto mensual" in digest and "Quedan 1 vacantes" in digest


def test_estado_sobrevive_como_dump_de_texto(tmp_root):
    # En Actions el checkout no trae el .db (está en .gitignore), solo radar.sql.
    run(tmp_root, FakeHttp(routes()), FakeScorer())
    (tmp_root / "data" / "radar.db").unlink()
    assert (tmp_root / "data" / "radar.sql").exists()
    scorer = FakeScorer()
    run(tmp_root, FakeHttp(routes()), scorer)
    assert scorer.calls == []
    assert len(rows(tmp_root)) == 8
