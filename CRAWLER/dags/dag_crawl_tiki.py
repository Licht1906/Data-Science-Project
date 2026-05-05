from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from airflow import DAG
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from psycopg2.extras import execute_batch

from CRAWLER.crawlers.product_crawler import DEFAULT_CATEGORIES, ProductCrawler
from CRAWLER.keywords_env import tiki_keywords_from_env as _keywords_from_env
from CRAWLER.crawlers.review_crawler import ReviewCrawler
from CRAWLER.crawlers.user_crawler import UserCrawler


default_args = {
    "owner": "N3-crawler",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
}


def crawl_products(**context):
    crawler = _build_product_crawler()
    hook = PostgresHook(postgres_conn_id="tiki_data")
    _ensure_crawl_history_table(hook)
    keywords = _keywords_from_env()
    excluded = _completed_product_ids_by_keyword(hook, keywords)
    products = crawler.discover_top_products_by_keyword(
        keywords=keywords,
        products_per_keyword=_env_int("CRAWLER_PRODUCTS_PER_KEYWORD", 10),
        search_pages=_env_int("CRAWLER_SEARCH_PAGES", 3),
        limit=_env_int("CRAWLER_PRODUCT_LIMIT", 40),
        excluded_product_ids=excluded,
    )
    if not products and os.getenv("CRAWLER_FALLBACK_TO_CATEGORIES", "false").lower() == "true":
        products = crawler.crawl_all(
            categories=_categories_from_env(),
            max_pages=_env_int("CRAWLER_MAX_PAGES", 2),
            limit=_env_int("CRAWLER_PRODUCT_LIMIT", 40),
        )
    _execute_batch(
        hook,
        """
        INSERT INTO raw_products (product_id, name, category, price, brand, rating_avg, review_count, url, crawled_at)
        VALUES (%(product_id)s, %(name)s, %(category)s, %(price)s, %(brand)s, %(rating_avg)s, %(review_count)s, %(url)s, NOW())
        ON CONFLICT (product_id) DO UPDATE SET
            name = EXCLUDED.name,
            category = EXCLUDED.category,
            price = EXCLUDED.price,
            brand = EXCLUDED.brand,
            rating_avg = EXCLUDED.rating_avg,
            review_count = EXCLUDED.review_count,
            url = EXCLUDED.url,
            crawled_at = NOW()
        """,
        products,
    )
    _execute_batch(
        hook,
        """
        INSERT INTO crawl_product_history (keyword, product_id, status, selected_at)
        VALUES (%(discovery_keyword)s, %(product_id)s, 'selected', NOW())
        ON CONFLICT (keyword, product_id) DO UPDATE SET
            status = CASE
                WHEN crawl_product_history.status = 'completed' THEN crawl_product_history.status
                ELSE 'selected'
            END,
            selected_at = NOW()
        """,
        [product for product in products if product.get("discovery_keyword")],
    )
    product_ids = [product["product_id"] for product in products]
    keyword_by_product = {product["product_id"]: product.get("discovery_keyword") for product in products}
    _upsert_metadata(hook, "last_product_count", str(len(product_ids)))
    _upsert_metadata(hook, "last_keywords", json.dumps(keywords, ensure_ascii=False))
    context["ti"].xcom_push(key="product_ids", value=product_ids)
    context["ti"].xcom_push(key="keyword_by_product", value=keyword_by_product)
    return len(product_ids)


def crawl_reviews(**context):
    product_ids = context["ti"].xcom_pull(task_ids="crawl_products", key="product_ids") or []
    keyword_by_product = context["ti"].xcom_pull(task_ids="crawl_products", key="keyword_by_product") or {}
    crawler = _build_review_crawler()
    product_cap = _env_int("CRAWLER_PRODUCT_CAP", 200)
    hook = PostgresHook(postgres_conn_id="tiki_data")
    _ensure_crawl_history_table(hook)
    reviews: list[dict] = []
    user_ids: set[str] = set()
    for product_id in product_ids[:product_cap]:
        product_reviews = crawler.crawl_product_reviews(
            product_id,
            max_pages=_env_int("CRAWLER_MAX_PAGES", 2),
            limit=_env_int("CRAWLER_REVIEW_LIMIT", 20),
            crawl_all_pages=os.getenv("CRAWLER_ALL_REVIEW_PAGES", "true").lower() == "true",
        )
        reviews.extend(product_reviews)
        for review in product_reviews:
            user_ids.add(review.get("user_id") or "")
        _insert_reviews(hook, product_reviews)
        keyword = keyword_by_product.get(product_id)
        if keyword:
            _mark_product_crawled(hook, keyword, product_id, len(product_reviews))
    _upsert_metadata(hook, "last_review_count", str(len(reviews)))
    context["ti"].xcom_push(key="user_ids", value=sorted(filter(None, user_ids)))
    return len(reviews)


def crawl_users(**context):
    user_ids = context["ti"].xcom_pull(task_ids="crawl_reviews", key="user_ids") or []
    crawler = _build_user_crawler()
    users = crawler.crawl_many(user_ids[: _env_int("CRAWLER_USER_CAP", 500)])
    hook = PostgresHook(postgres_conn_id="tiki_data")
    _execute_batch(
        hook,
        """
        INSERT INTO raw_users (user_id, name, join_date, total_reviews, avg_rating_given, crawled_at)
        VALUES (%(user_id)s, %(name)s, %(join_date)s, %(total_reviews)s, %(avg_rating_given)s, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            name = EXCLUDED.name,
            join_date = COALESCE(EXCLUDED.join_date, raw_users.join_date),
            total_reviews = EXCLUDED.total_reviews,
            avg_rating_given = EXCLUDED.avg_rating_given,
            crawled_at = NOW()
        """,
        users,
    )
    _upsert_metadata(hook, "last_user_count", str(len(users)))
    return len(users)


def data_quality_check():
    hook = PostgresHook(postgres_conn_id="tiki_data")
    result = hook.get_first(
        """
        SELECT
            COUNT(*) AS total_reviews,
            COUNT(*) - COUNT(DISTINCT review_id) AS duplicate_reviews,
            SUM(CASE WHEN content IS NULL OR trim(content) = '' THEN 1 ELSE 0 END) AS empty_content
        FROM raw_reviews
        """
    )
    summary = {"total_reviews": result[0], "duplicate_reviews": result[1], "empty_content": result[2]}
    _upsert_metadata(hook, "last_quality_summary", json.dumps(summary, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def _build_product_crawler() -> ProductCrawler:
    return ProductCrawler(output_dir=_checkpoint_dir(), delay_range=_delay_range(), retries=_env_int("CRAWLER_RETRIES", 3), timeout=_env_int("CRAWLER_TIMEOUT", 20))


def _build_review_crawler() -> ReviewCrawler:
    return ReviewCrawler(output_dir=_checkpoint_dir(), delay_range=_delay_range(), retries=_env_int("CRAWLER_RETRIES", 3), timeout=_env_int("CRAWLER_TIMEOUT", 20))


def _build_user_crawler() -> UserCrawler:
    return UserCrawler(output_dir=_checkpoint_dir(), delay_range=_delay_range(), retries=_env_int("CRAWLER_RETRIES", 3), timeout=_env_int("CRAWLER_TIMEOUT", 20))


def _checkpoint_dir() -> str:
    return os.getenv("CRAWLER_CHECKPOINT_DIR", "/opt/airflow/logs/tiki_checkpoints")


def _delay_range() -> tuple[float, float]:
    return (float(os.getenv("CRAWLER_DELAY_MIN", "2")), float(os.getenv("CRAWLER_DELAY_MAX", "5")))


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _categories_from_env() -> dict[str, int]:
    raw = os.getenv("TIKI_CATEGORIES_JSON")
    if not raw:
        return DEFAULT_CATEGORIES
    parsed = json.loads(raw)
    return {str(name): int(category_id) for name, category_id in parsed.items()}


def _completed_product_ids_by_keyword(hook: PostgresHook, keywords: list[str]) -> set[str]:
    if not keywords:
        return set()
    rows = hook.get_records(
        """
        SELECT product_id
        FROM crawl_product_history
        WHERE status IN ('completed', 'no_comments') AND keyword = ANY(%(keywords)s)
        """,
        parameters={"keywords": keywords},
    )
    return {str(row[0]) for row in rows}


def _ensure_crawl_history_table(hook: PostgresHook) -> None:
    hook.run(
        """
        CREATE TABLE IF NOT EXISTS crawl_product_history (
            keyword TEXT NOT NULL,
            product_id TEXT NOT NULL REFERENCES raw_products(product_id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'discovered',
            selected_at TIMESTAMP DEFAULT NOW(),
            completed_at TIMESTAMP,
            review_count INTEGER DEFAULT 0,
            PRIMARY KEY (keyword, product_id)
        )
        """
    )
    hook.run("CREATE INDEX IF NOT EXISTS idx_crawl_history_keyword_status ON crawl_product_history(keyword, status)")


def _mark_product_crawled(hook: PostgresHook, keyword: str, product_id: str, review_count: int) -> None:
    hook.run(
        """
        UPDATE crawl_product_history
        SET status = %(status)s,
            completed_at = NOW(),
            review_count = %(review_count)s
        WHERE keyword = %(keyword)s AND product_id = %(product_id)s
        """,
        parameters={
            "keyword": keyword,
            "product_id": product_id,
            "review_count": review_count,
            "status": "completed" if review_count > 0 else "no_comments",
        },
    )


def _insert_reviews(hook: PostgresHook, reviews: list[dict]) -> None:
    _execute_batch(
        hook,
        """
        INSERT INTO raw_reviews (review_id, product_id, user_id, rating, content, created_at, helpful_count, purchased, title, crawled_at)
        VALUES (%(review_id)s, %(product_id)s, %(user_id)s, %(rating)s, %(content)s, %(created_at)s, %(helpful_count)s, %(purchased)s, %(title)s, NOW())
        ON CONFLICT (review_id) DO UPDATE SET
            rating = EXCLUDED.rating,
            content = EXCLUDED.content,
            helpful_count = EXCLUDED.helpful_count,
            purchased = EXCLUDED.purchased,
            title = EXCLUDED.title
        """,
        reviews,
    )


def _execute_batch(hook: PostgresHook, sql: str, rows: list[dict]) -> None:
    if not rows:
        return
    conn = hook.get_conn()
    try:
        with conn.cursor() as cursor:
            execute_batch(cursor, sql, rows, page_size=_env_int("DB_BATCH_SIZE", 500))
        conn.commit()
    finally:
        conn.close()


def _upsert_metadata(hook: PostgresHook, key: str, value: str) -> None:
    hook.run(
        """
        INSERT INTO crawl_metadata (crawl_key, last_value, updated_at)
        VALUES (%(crawl_key)s, %(last_value)s, NOW())
        ON CONFLICT (crawl_key) DO UPDATE SET
            last_value = EXCLUDED.last_value,
            updated_at = NOW()
        """,
        parameters={"crawl_key": key, "last_value": value},
    )


with DAG(
    dag_id="dag_crawl_tiki",
    default_args=default_args,
    description="DAG 1: crawl trending product keywords from Tiki every hour.",
    schedule_interval=os.getenv("CRAWLER_SCHEDULE", "0 * * * *"),
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["tiki", "crawl"],
) as dag:
    crawl_products_task = PythonOperator(task_id="crawl_products", python_callable=crawl_products)
    crawl_reviews_task = PythonOperator(task_id="crawl_reviews", python_callable=crawl_reviews)
    crawl_users_task = PythonOperator(task_id="crawl_users", python_callable=crawl_users)
    quality_task = PythonOperator(task_id="data_quality_check", python_callable=data_quality_check)
    trigger_clean_label = TriggerDagRunOperator(
        task_id="trigger_clean_label",
        trigger_dag_id="dag_clean_label",
        reset_dag_run=True,
        wait_for_completion=False,
    )

    crawl_products_task >> crawl_reviews_task >> crawl_users_task >> quality_task >> trigger_clean_label
