import time
import json
import random
import logging
import requests
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


class BaseCrawler:
    """
    Base class cho tất cả Tiki crawlers.
    Cung cấp: retry logic, random delay, header rotation, checkpoint.
    """

    def __init__(
        self,
        checkpoint_path: str = "checkpoints/base.json",
        max_retries: int = 3,
        delay_min: float = 2.0,
        delay_max: float = 5.0,
    ):
        self.checkpoint_path = Path(checkpoint_path)
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.session = requests.Session()
        self.checkpoint = self._load_checkpoint()

    # ------------------------------------------------------------------ #
    # Checkpoint
    # ------------------------------------------------------------------ #

    def _load_checkpoint(self) -> dict:
        if self.checkpoint_path.exists():
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"Loaded checkpoint: {self.checkpoint_path}")
            return data
        return {}

    def save_checkpoint(self, data: dict):
        with open(self.checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.checkpoint = data
        logger.debug(f"Checkpoint saved: {self.checkpoint_path}")

    # ------------------------------------------------------------------ #
    # HTTP
    # ------------------------------------------------------------------ #

    def _get_headers(self) -> dict:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://tiki.vn/",
            "x-guest-token": self._generate_guest_token(),
        }

    @staticmethod
    def _generate_guest_token() -> str:
        """Tạo guest token giả để tránh bị block."""
        chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return "".join(random.choices(chars, k=40))

    def get(self, url: str, params: Optional[dict] = None) -> Optional[dict]:
        """
        Gọi GET request với retry và delay tự động.
        Trả về JSON dict hoặc None nếu thất bại sau max_retries lần.
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                self._random_delay()
                response = self.session.get(
                    url,
                    params=params,
                    headers=self._get_headers(),
                    timeout=15,
                )
                response.raise_for_status()
                return response.json()

            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else "?"
                logger.warning(f"[Attempt {attempt}/{self.max_retries}] HTTP {status} — {url}")
                if status == 429:
                    # Rate limited: đợi lâu hơn
                    time.sleep(10 * attempt)
                elif status in (403, 404):
                    # Không cần retry
                    return None

            except requests.exceptions.RequestException as e:
                logger.warning(f"[Attempt {attempt}/{self.max_retries}] Request error: {e}")

            if attempt < self.max_retries:
                time.sleep(2 ** attempt)  # exponential backoff

        logger.error(f"Failed after {self.max_retries} attempts: {url}")
        return None

    def _random_delay(self):
        delay = random.uniform(self.delay_min, self.delay_max)
        logger.debug(f"Sleeping {delay:.1f}s...")
        time.sleep(delay)