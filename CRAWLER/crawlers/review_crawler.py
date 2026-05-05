from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from CRAWLER.crawlers.base_crawler import BaseCrawler
from PREPROCESSING.nlp_utils import clean_text


class ReviewCrawler(BaseCrawler):
    def crawl_product_reviews(
        self,
        product_id: str,
        max_pages: int = 2,
        since: datetime | None = None,
        limit: int = 20,
        crawl_all_pages: bool = False,
    ) -> list[dict[str, Any]]:
        reviews: list[dict[str, Any]] = []
        page = 1
        while page <= max_pages:
            payload = self.get_json(
                "reviews",
                params={
                    "product_id": product_id,
                    "limit": limit,
                    "page": page,
                    "include": "comments,contribute_info,attribute_vote_summary",
                },
            )
            page_reviews = payload.get("data", [])
            if not page_reviews:
                break
            for item in page_reviews:
                normalized = self._normalize_review(item, product_id)
                if not clean_text(normalized.get("content")):
                    continue
                if since and normalized["created_at"] and normalized["created_at"] <= since:
                    continue
                reviews.append(normalized)
            if crawl_all_pages:
                last_page = int((payload.get("paging") or {}).get("last_page") or page)
                if page >= last_page:
                    break
                max_pages = max(max_pages, last_page)
            page += 1
        return reviews

    def crawl_many(
        self,
        product_ids: list[str],
        max_pages: int = 2,
        since: datetime | None = None,
        limit: int = 20,
        crawl_all_pages: bool = False,
    ) -> list[dict[str, Any]]:
        all_reviews: list[dict[str, Any]] = []
        for product_id in product_ids:
            all_reviews.extend(
                self.crawl_product_reviews(
                    product_id,
                    max_pages=max_pages,
                    since=since,
                    limit=limit,
                    crawl_all_pages=crawl_all_pages,
                )
            )
        self.save_checkpoint("last_review_count", {"count": len(all_reviews)})
        return all_reviews

    @staticmethod
    def _normalize_review(item: dict[str, Any], product_id: str) -> dict[str, Any]:
        created = item.get("created_at") or item.get("created_time")
        created_at = None
        if isinstance(created, int):
            created_at = datetime.fromtimestamp(created, tz=timezone.utc).replace(tzinfo=None)
        elif isinstance(created, str):
            try:
                created_at = datetime.fromisoformat(created.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                created_at = None

        user = item.get("created_by") or item.get("customer") or item.get("user") or {}
        review_id = item.get("id") or item.get("review_id") or item.get("comment_id")
        return {
            "review_id": str(review_id or f"{product_id}-{created or ''}-{user.get('id') or item.get('customer_id') or ''}"),
            "product_id": str(product_id),
            "user_id": str(user.get("id") or item.get("customer_id") or ""),
            "rating": item.get("rating"),
            "content": item.get("content") or item.get("comment") or "",
            "created_at": created_at,
            "helpful_count": item.get("thank_count") or item.get("helpful_count") or 0,
            "purchased": bool(item.get("is_buyer") or item.get("is_purchased")),
            "title": item.get("title") or "",
            "user_name": user.get("name") or "",
            "total_reviews": user.get("reviews_count") or user.get("total_reviews") or 0,
        }
