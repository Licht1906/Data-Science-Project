from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from CRAWLER.crawlers.base_crawler import BaseCrawler


class UserCrawler(BaseCrawler):
    def crawl_user(self, user_id: str) -> dict[str, Any]:
        try:
            payload = self.get_json(f"customers/{user_id}")
        except RuntimeError:
            payload = {}
        return self._normalize_user(payload, user_id)

    def crawl_many(self, user_ids: list[str]) -> list[dict[str, Any]]:
        users = [self.crawl_user(user_id) for user_id in sorted(set(filter(None, user_ids)))]
        self.save_checkpoint("last_user_count", {"count": len(users)})
        return users

    @staticmethod
    def _normalize_user(item: dict[str, Any], user_id: str) -> dict[str, Any]:
        join_date = _parse_datetime(item.get("created_at") or item.get("joined_at") or item.get("created_time"))
        return {
            "user_id": str(item.get("id") or user_id),
            "name": item.get("name") or item.get("full_name") or "",
            "join_date": join_date,
            "total_reviews": item.get("reviews_count") or item.get("total_reviews") or 0,
            "avg_rating_given": item.get("avg_rating_given"),
        }


def _parse_datetime(value: Any):
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None
