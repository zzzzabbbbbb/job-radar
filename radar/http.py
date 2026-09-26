"""Cliente HTTP compartido: User-Agent identificable y un segundo entre peticiones."""
from __future__ import annotations

import time

import requests

USER_AGENT = "job-radar/1.0 (personal job search; +https://github.com/zzzzabbbbbb/job-radar)"
MIN_INTERVAL_S = 1.0
TIMEOUT_S = 30


class FetchError(Exception):
    pass


class Http:
    def __init__(self, min_interval: float = MIN_INTERVAL_S):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self.min_interval = min_interval
        self._last = 0.0

    def _throttle(self) -> None:
        wait = self._last + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def get_json(self, url: str, params: dict | None = None):
        """GET con un reintento ante timeouts o 5xx. Cualquier otra falla levanta FetchError."""
        last_err: Exception | None = None
        for attempt in range(2):
            self._throttle()
            try:
                resp = self.session.get(url, params=params, timeout=TIMEOUT_S)
            except requests.RequestException as e:
                last_err = FetchError(f"{type(e).__name__} al conectar con {url.split('/')[2]}")
                continue
            if resp.status_code == 404:
                raise FetchError(f"404 en {url} (¿token/slug incorrecto o board cerrado?)")
            if resp.status_code >= 500 or resp.status_code == 429:
                last_err = FetchError(f"HTTP {resp.status_code} en {url}")
                if attempt == 0:
                    time.sleep(5)
                continue
            if resp.status_code != 200:
                raise FetchError(f"HTTP {resp.status_code} en {url}")
            try:
                return resp.json()
            except ValueError as e:
                raise FetchError(f"Respuesta no es JSON en {url}: {e}") from e
        raise FetchError(str(last_err))
