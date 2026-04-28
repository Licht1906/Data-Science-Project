import logging
import psycopg2
from datetime import datetime
from typing import Optional
from .base_crawler import BaseCrawler

logger = logging.getLogger(__name__)

REVIEW_URL = "https://tiki.vn/api/v2/reviews"


class ReviewCrawler(BaseCrawler):
    """
    Crawl reviews theo product_id.
    Hỗ trợ incremental: chỉ lấy reviews mới hơn last_crawl_time.
    """

    def __init__(self, db_conn: psycopg2.extensions.connection, **kwargs):
        super().__init__(checkpoint_path="checkpoints/reviews.json", **kwargs)
        self.conn = db_conn
        self.cursor = db_conn.cursor()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def crawl_products(self, product_ids: list[int]) -> list[int]:
        """
        Crawl reviews cho danh sách product_ids.
        Trả về list user_ids xuất hiện trong reviews (để UserCrawler dùng).
        """
        all_user_ids = []
        done_products = set(self.checkpoint.get("done_products", []))
        total = len(product_ids)

        for i, product_id in enumerate(product_ids, 1):
            if product_id in done_products:
                logger.debug(f"[SKIP] product {product_id} already done")
                continue

            logger.info(f"[{i}/{total}] Crawling reviews for product {product_id}")
            last_crawl = self._get_last_crawl_time(product_id)
            user_ids = self._crawl_product_reviews(product_id, last_crawl)
            all_user_ids.extend(user_ids)

            done_products.add(product_id)
            self.save_checkpoint({"done_products": list(done_products)})

        return list(set(all_user_ids))  # Deduplicate

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _crawl_product_reviews(
        self, product_id: int, last_crawl_time: Optional[datetime]
    ) -> list[int]:
        """Crawl tất cả trang reviews cho 1 sản phẩm. Trả về user_ids."""
        user_ids = []
        page = 1
        page_size = 20  # Tiki trả tối đa 20 reviews/trang
        stop_flag = False  # Dừng khi gặp review cũ hơn last_crawl_time

        while not stop_flag:
            params = {
                "product_id": product_id,
                "page": page,
                "limit": page_size,
                "sort": "score|desc,id|desc,stars|all",
                "include": "comments,contribute_info,attribute_vote_summary",
            }
            data = self.get(REVIEW_URL, params=params)

            if not data:
                break

            reviews = data.get("data", [])
            if not reviews:
                break

            for review in reviews:
                review_time = self._parse_created_at(review.get("created_at"))

                # Incremental: dừng nếu review cũ hơn lần crawl trước
                if last_crawl_time and review_time and review_time <= last_crawl_time:
                    stop_flag = True
                    break

                uid = self._save_review(review, product_id)
                if uid:
                    user_ids.append(uid)

            self.conn.commit()
            logger.debug(f"  product {product_id} page {page}: {len(reviews)} reviews")

            # Kiểm tra còn trang không
            paging = data.get("paging", {})
            if page >= paging.get("last_page", 1):
                break
            page += 1

        # Cập nhật last_crawl_time cho product này
        self._update_crawl_metadata(product_id)
        return user_ids

    def _save_review(self, review: dict, product_id: int) -> Optional[int]:
        review_id = review.get("id")
        if not review_id:
            return None

        created_by = review.get("created_by", {})
        user_id = created_by.get("id")

        sql = """
            INSERT INTO raw_reviews (
                review_id, product_id, user_id, rating, title, content,
                purchased_at, thank_count, is_anonymous,
                created_at, crawled_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (review_id) DO NOTHING
        """
        try:
            self.cursor.execute(sql, (
                review_id,
                product_id,
                user_id,
                review.get("rating"),
                review.get("title"),
                review.get("content"),
                review.get("purchased_at"),
                review.get("thank_count", 0),
                review.get("is_anonymous", False),
                self._parse_created_at(review.get("created_at")),
                datetime.utcnow(),
            ))
            return user_id
        except Exception as e:
            logger.error(f"DB error saving review {review_id}: {e}")
            self.conn.rollback()
            return None

    def _get_last_crawl_time(self, product_id: int) -> Optional[datetime]:
        self.cursor.execute(
            "SELECT last_crawl_time FROM crawl_metadata WHERE product_id = %s",
            (product_id,)
        )
        row = self.cursor.fetchone()
        return row[0] if row else None

    def _update_crawl_metadata(self, product_id: int):
        sql = """
            INSERT INTO crawl_metadata (product_id, last_crawl_time)
            VALUES (%s, %s)
            ON CONFLICT (product_id) DO UPDATE SET last_crawl_time = EXCLUDED.last_crawl_time
        """
        try:
            self.cursor.execute(sql, (product_id, datetime.utcnow()))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error updating crawl_metadata for {product_id}: {e}")

    @staticmethod
    def _parse_created_at(value) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, int):
            # Unix timestamp
            return datetime.utcfromtimestamp(value)
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None