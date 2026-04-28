import logging
import psycopg2
from datetime import datetime
from typing import Optional
from .base_crawler import BaseCrawler

logger = logging.getLogger(__name__)

# 8 danh mục theo yêu cầu: category_id lấy từ URL Tiki
CATEGORIES = {
    "dien-thoai":       1789,
    "laptop":           8095,
    "do-gia-dung":      1883,
    "thoi-trang-nam":   931,
    "sach":             8322,
    "my-pham":          44792,
    "the-thao":         1975,
    "do-choi":          2549,
}

LISTING_URL = "https://tiki.vn/api/personalish/v1/blocks/listings"


class ProductCrawler(BaseCrawler):
    """
    Crawl danh sách sản phẩm từ 8 danh mục Tiki.
    Mục tiêu: 500–1000 sản phẩm, lưu vào bảng raw_products.
    """

    def __init__(self, db_conn: psycopg2.extensions.connection, **kwargs):
        super().__init__(checkpoint_path="checkpoints/products.json", **kwargs)
        self.conn = db_conn
        self.cursor = db_conn.cursor()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def crawl_all(self, max_per_category: int = 150) -> list[int]:
        """
        Crawl tất cả danh mục. Trả về list product_ids đã crawl được.
        Dùng checkpoint để tiếp tục nếu bị gián đoạn.
        """
        all_product_ids = []
        done_categories = set(self.checkpoint.get("done_categories", []))

        for slug, category_id in CATEGORIES.items():
            if slug in done_categories:
                logger.info(f"[SKIP] {slug} already done (checkpoint)")
                # Vẫn cần trả về product_ids đã lưu trong DB
                all_product_ids.extend(self._get_saved_ids(category_id))
                continue

            logger.info(f"[START] Crawling category: {slug} (id={category_id})")
            ids = self._crawl_category(category_id, slug, max_per_category)
            all_product_ids.extend(ids)

            done_categories.add(slug)
            self.save_checkpoint({"done_categories": list(done_categories)})
            logger.info(f"[DONE] {slug}: {len(ids)} products")

        return all_product_ids

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _crawl_category(self, category_id: int, slug: str, max_count: int) -> list[int]:
        product_ids = []
        page = 1
        page_size = 40  # Tiki trả tối đa 40/trang

        while len(product_ids) < max_count:
            params = {
                "limit": page_size,
                "category": category_id,
                "page": page,
                "sort": "top_seller",
            }
            data = self.get(LISTING_URL, params=params)

            if not data:
                logger.warning(f"No data returned for {slug} page {page}")
                break

            items = data.get("data", [])
            if not items:
                logger.info(f"No more items for {slug} at page {page}")
                break

            for item in items:
                pid = self._save_product(item, slug)
                if pid:
                    product_ids.append(pid)

            # Commit sau mỗi trang
            self.conn.commit()
            logger.info(f"  {slug} page {page}: +{len(items)} products (total={len(product_ids)})")
            page += 1

        return product_ids

    def _save_product(self, item: dict, category_slug: str) -> Optional[int]:
        product_id = item.get("id")
        if not product_id:
            return None

        sql = """
            INSERT INTO raw_products (
                product_id, name, category_slug, brand, price,
                rating_average, review_count, url_path, thumbnail_url,
                crawled_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (product_id) DO UPDATE SET
                price           = EXCLUDED.price,
                rating_average  = EXCLUDED.rating_average,
                review_count    = EXCLUDED.review_count,
                crawled_at      = EXCLUDED.crawled_at
        """
        try:
            self.cursor.execute(sql, (
                product_id,
                item.get("name"),
                category_slug,
                item.get("brand_name"),
                item.get("price"),
                item.get("rating_average"),
                item.get("review_count", 0),
                item.get("url_path"),
                item.get("thumbnail_url"),
                datetime.utcnow(),
            ))
            return product_id
        except Exception as e:
            logger.error(f"DB error saving product {product_id}: {e}")
            self.conn.rollback()
            return None

    def _get_saved_ids(self, category_id: int) -> list[int]:
        """Lấy product_ids đã có trong DB (cho checkpoint resume)."""
        # Ánh xạ category_id -> slug để query
        slug = next((s for s, cid in CATEGORIES.items() if cid == category_id), None)
        if not slug:
            return []
        self.cursor.execute(
            "SELECT product_id FROM raw_products WHERE category_slug = %s",
            (slug,)
        )
        return [row[0] for row in self.cursor.fetchall()]