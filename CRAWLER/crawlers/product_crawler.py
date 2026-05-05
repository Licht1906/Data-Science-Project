from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from CRAWLER.crawlers.base_crawler import BaseCrawler


DEFAULT_CATEGORIES = {
    "dien-thoai": 1789,
    "laptop": 8095,
    "do-gia-dung": 1882,
    "thoi-trang-nam": 915,
    "sach": 8322,
    "my-pham": 1520,
    "the-thao": 1975,
    "do-choi": 2549,
}

DEFAULT_KEYWORDS = [
    "điện thoại",
    "iphone",
    "samsung",
    "xiaomi",
    "oppo",
    "tai nghe bluetooth",
    "loa bluetooth",
    "sạc dự phòng",
    "cáp sạc",
    "ốp lưng điện thoại",
    "laptop",
    "máy tính bảng",
    "ipad",
    "màn hình máy tính",
    "bàn phím cơ",
    "chuột không dây",
    "webcam",
    "ổ cứng ssd",
    "usb",
    "máy in",
    "tivi",
    "máy lạnh",
    "tủ lạnh",
    "máy giặt",
    "máy lọc không khí",
    "nồi chiên không dầu",
    "nồi cơm điện",
    "máy hút bụi",
    "quạt điện",
    "máy xay sinh tố",
    "mỹ phẩm",
    "kem chống nắng",
    "sữa rửa mặt",
    "serum",
    "son môi",
    "nước hoa",
    "dầu gội",
    "sữa tắm",
    "kem dưỡng da",
    "mặt nạ dưỡng da",
    "sách",
    "sách kỹ năng",
    "sách kinh tế",
    "sách thiếu nhi",
    "truyện tranh",
    "văn phòng phẩm",
    "bút bi",
    "sổ tay",
    "balo laptop",
    "đèn học",
    "thời trang nữ",
    "thời trang nam",
    "áo thun",
    "áo khoác",
    "quần jean",
    "giày sneaker",
    "dép",
    "túi xách",
    "đồng hồ",
    "kính mát",
    "mẹ và bé",
    "bỉm",
    "sữa bột",
    "đồ chơi trẻ em",
    "xe đẩy em bé",
    "bình sữa",
    "khăn ướt",
    "ghế ăn dặm",
    "sữa tắm em bé",
    "đồ sơ sinh",
    "thực phẩm chức năng",
    "vitamin",
    "collagen",
    "omega 3",
    "protein",
    "cà phê",
    "trà",
    "bánh kẹo",
    "ngũ cốc",
    "nước giặt",
]


class ProductCrawler(BaseCrawler):
    def search_products(self, keyword: str, max_pages: int = 3, limit: int = 40) -> list[dict[str, Any]]:
        products: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            payload = self.get_json(
                "products",
                params={
                    "q": keyword,
                    "limit": limit,
                    "page": page,
                    "sort": "top_seller",
                    "include": "advertisement",
                },
            )
            items = payload.get("data", [])
            if not items:
                break
            for item in items:
                products.append(self._normalize_product(item, keyword))
        return products

    def discover_top_products_by_keyword(
        self,
        keywords: list[str],
        products_per_keyword: int = 10,
        search_pages: int = 3,
        limit: int = 40,
        excluded_product_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        excluded = excluded_product_ids or set()
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for keyword in keywords:
            candidates = [
                product
                for product in self.search_products(keyword, max_pages=search_pages, limit=limit)
                if product["product_id"] and product["product_id"] not in excluded and product["product_id"] not in seen
            ]
            candidates.sort(key=lambda product: (int(product.get("sold_count") or 0), int(product.get("review_count") or 0)), reverse=True)
            for product in candidates[:products_per_keyword]:
                product["discovery_keyword"] = keyword
                selected.append(product)
                seen.add(product["product_id"])
        self.save_checkpoint("last_keyword_product_ids", [product["product_id"] for product in selected])
        return selected

    def crawl_category(self, category_name: str, category_id: int, max_pages: int = 2, limit: int = 40) -> list[dict[str, Any]]:
        products: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            payload = self.get_json(
                "products",
                params={
                    "limit": limit,
                    "page": page,
                    "category": category_id,
                    "include": "advertisement",
                },
            )
            items = payload.get("data", [])
            if not items:
                break
            for item in items:
                products.append(self._normalize_product(item, category_name))
        return products

    def crawl_all(
        self,
        categories: dict[str, int] | None = None,
        max_pages: int = 2,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        selected = categories or DEFAULT_CATEGORIES
        seen: set[str] = set()
        products: list[dict[str, Any]] = []

        for category_name, category_id in selected.items():
            for product in self.crawl_category(category_name, category_id, max_pages=max_pages, limit=limit):
                product_id = product["product_id"]
                if product_id and product_id not in seen:
                    products.append(product)
                    seen.add(product_id)

        self.save_checkpoint("last_product_ids", sorted(seen))
        return products

    @staticmethod
    def product_id_from_url(url: str) -> str | None:
        match = re.search(r"-p(\d+)\.html", url)
        if match:
            return match.group(1)
        match = re.search(r"(?:spid|product_id|p)(?:=|-)(\d+)", url)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _normalize_product(item: dict[str, Any], category_name: str) -> dict[str, Any]:
        product_id = item.get("id") or item.get("spid") or item.get("master_id")
        quantity_sold = item.get("quantity_sold")
        sold_count = quantity_sold.get("value", 0) if isinstance(quantity_sold, dict) else 0
        url = item.get("url_path") or item.get("url") or ""
        if url and not str(url).startswith("http"):
            url = urljoin("https://tiki.vn/", str(url).lstrip("/"))
        return {
            "product_id": str(product_id or ""),
            "name": item.get("name") or "",
            "category": category_name,
            "price": item.get("price"),
            "brand": (item.get("brand") or {}).get("name") if isinstance(item.get("brand"), dict) else item.get("brand"),
            "rating_avg": item.get("rating_average"),
            "review_count": _parse_count(item.get("review_count") or item.get("review_count_text")),
            "sold_count": sold_count,
            "url": url,
        }


def _parse_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"\D+", "", str(value))
    return int(digits) if digits else 0
