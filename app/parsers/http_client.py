import json
import logging
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.util.retry import Retry

from app.core.config import settings


class HttpClient:
    def __init__(self, site_key: str) -> None:
        self._site_key = site_key
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "WardrobeParser/1.0"})
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._load_cookies()

    def get(self, url: str, timeout_sec: int) -> requests.Response:
        backoff = 1.0
        while True:
            try:
                return self._session.get(url, timeout=timeout_sec)
            except RequestException as exc:
                logging.warning("HttpClient retry: url=%s error=%s", url, exc)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    def _load_cookies(self) -> None:
        cookies_dir = Path(settings.cookies_dir)
        cookie_file = cookies_dir / f"{self._site_key}.json"
        if not cookie_file.exists():
            return
        try:
            data = json.loads(cookie_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        if isinstance(data, dict):
            self._session.cookies.update(data)
            return
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                value = item.get("value")
                domain = item.get("domain")
                path = item.get("path", "/")
                if name and value:
                    self._session.cookies.set(name, value, domain=domain, path=path)


def ensure_cookies_dir() -> Path:
    cookies_dir = Path(settings.cookies_dir)
    cookies_dir.mkdir(parents=True, exist_ok=True)
    return cookies_dir
