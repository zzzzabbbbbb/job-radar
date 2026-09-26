from types import SimpleNamespace

from radar.scorer import cost_of, enforce_guardrails


def base(**kw):
    s = {"fit_score": 80, "verdict": "apply_now", "matches": [], "gaps": [], "blockers": [],
         "seniority_read": "at_level", "one_line": ""}
    s.update(kw)
    return s


def test_blocker_fuerza_score_menor_a_30():
    s = enforce_guardrails(base(blockers=["Pide 7 años"]))
    assert s["fit_score"] < 30 and s["verdict"] == "skip"


def test_skip_nunca_llega_al_digest():
    assert enforce_guardrails(base(verdict="skip", fit_score=90))["fit_score"] < 65


def test_score_acotado():
    assert enforce_guardrails(base(fit_score=140))["fit_score"] == 100


def test_costo():
    usage = SimpleNamespace(input_tokens=1000, output_tokens=500,
                            cache_creation_input_tokens=0, cache_read_input_tokens=2000)
    # opus 5: 1000*5 + 500*25 + 2000*0.5 = 18500 / 1e6
    assert abs(cost_of(usage, "claude-opus-5") - 0.0185) < 1e-9
