import json
from pathlib import Path
from typing import Any

import requests

from app.core.config import settings


class HttpClient:
    def __init__(self, site_key: str) -> None:
        self._site_key = site_key
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "WardrobeParser/1.0"})
        self._load_cookies()

    def get(self, url: str, timeout_sec: int) -> requests.Response:
        return self._session.get(url, timeout=timeout_sec)

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
