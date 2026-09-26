import json
import shutil
from pathlib import Path

import pytest
import yaml

from radar.http import FetchError

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


class FakeHttp:
    """Responde con fixtures según la URL; lo que no conoce es 404."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls = []

    def get_json(self, url, params=None):
        self.calls.append(url)
        for fragment, payload in self.routes.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise FetchError(f"404 en {url}")


@pytest.fixture
def settings():
    s = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
    s["prefilter"]["max_age_days"] = 100_000  # los fixtures tienen fechas fijas
    return s


@pytest.fixture
def tmp_root(tmp_path, settings):
    """Copia de config/ con empresas de prueba, para correr el pipeline completo."""
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config" / "profile.yaml", tmp_path / "config" / "profile.yaml")
    (tmp_path / "config" / "settings.yaml").write_text(yaml.safe_dump(settings))
    companies = [
        {"name": "Acme", "ats": "greenhouse", "token": "acme", "tier": 1},
        {"name": "Globex", "ats": "lever", "token": "globex", "tier": 1},
        {"name": "Rota", "ats": "greenhouse", "token": "rota", "tier": 2},
        {"name": "Futura", "ats": "workday", "token": "futura", "tier": 2},
    ]
    (tmp_path / "config" / "companies.yaml").write_text(yaml.safe_dump(companies))
    return tmp_path
