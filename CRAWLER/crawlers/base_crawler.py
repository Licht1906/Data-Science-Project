from __future__ import annotations

import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


class BaseCrawler:
    """Shared retry, delay and checkpoint behavior for Tiki crawlers."""

    USER_AGENTS = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/119 Safari/537.36",
    ]

    def __init__(
        self,
        base_url: str = "https://tiki.vn/api/v2",
        output_dir: str | Path = "data/checkpoints",
        timeout: int = 20,
        retries: int = 3,
        delay_range: tuple[float, float] = (2.0, 5.0),
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.output_dir = Path(output_dir)
        self.timeout = timeout
        self.retries = retries
        self.delay_range = delay_range
        self.session = requests.Session()
        self.session.trust_env = os.getenv("CRAWLER_TRUST_ENV_PROXY", "true").lower() == "true"
        self.extra_headers = _headers_from_env()
        proxy_url = os.getenv("CRAWLER_PROXY_URL")
        if proxy_url:
            self.session.proxies.update({"http": proxy_url, "https": proxy_url})
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        last_error: Exception | None = None

        for attempt in range(1, self.retries + 1):
            try:
                self._polite_delay(attempt)
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    headers={**self.extra_headers, "User-Agent": random.choice(self.USER_AGENTS)},
                )
                if response.status_code in {403, 429}:
                    self._rate_limit_delay(response, attempt)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                LOGGER.warning("GET %s failed on attempt %s/%s: %s", url, attempt, self.retries, exc)

        raise RuntimeError(f"Cannot fetch {url}") from last_error

    def load_checkpoint(self, key: str, default: Any = None) -> Any:
        path = self.output_dir / f"{key}.json"
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def save_checkpoint(self, key: str, value: Any) -> None:
        path = self.output_dir / f"{key}.json"
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def _polite_delay(self, attempt: int) -> None:
        low, high = self.delay_range
        backoff = max(0, attempt - 1) * 0.75
        time.sleep(random.uniform(low, high) + backoff)

    @staticmethod
    def _rate_limit_delay(response: requests.Response, attempt: int) -> None:
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            time.sleep(min(int(retry_after), 120))
        else:
            time.sleep(min(2**attempt, 60))


def _headers_from_env() -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": os.getenv("CRAWLER_ACCEPT_LANGUAGE", "vi-VN,vi;q=0.9,en;q=0.8"),
        "Referer": os.getenv("CRAWLER_REFERER", "https://tiki.vn/"),
    }
    cookie = os.getenv("TIKI_COOKIE")
    if cookie:
        headers["Cookie"] = cookie
    return headers
