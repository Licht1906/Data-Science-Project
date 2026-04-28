"""
DAG 1: dag_crawl_tiki
Chạy hàng ngày lúc 2:00 AM.
Flow: crawl_products → crawl_reviews → crawl_users → data_quality_check
XCom: product_ids (products→reviews), user_ids (reviews→users)
"""

import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.hooks.postgres_hook import PostgresHook

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# DAG config
# ------------------------------------------------------------------ #

default_args = {
    "owner": "n3-crawler",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}

dag = DAG(
    dag_id="dag_crawl_tiki",
    description="Crawl products, reviews, users từ Tiki",
    default_args=default_args,
    start_date=datetime(2024, 1, 1),
    schedule_interval="0 2 * * *",  # 2:00 AM mỗi ngày
    catchup=False,
    tags=["tiki", "crawl", "n3"],
)


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def get_db_conn():
    """Lấy kết nối PostgreSQL qua Airflow connection 'tiki_data'."""
    hook = PostgresHook(postgres_conn_id="tiki_data")
    return hook.get_conn()


# ------------------------------------------------------------------ #
# Task 1: crawl_products
# ------------------------------------------------------------------ #

def task_crawl_products(**context):
    import sys
    sys.path.insert(0, "/opt/airflow")
    from crawlers import ProductCrawler

    conn = get_db_conn()
    crawler = ProductCrawler(db_conn=conn, delay_min=2.0, delay_max=5.0)

    logger.info("Starting product crawl...")
    product_ids = crawler.crawl_all(max_per_category=150)

    logger.info(f"Crawled {len(product_ids)} products total")

    # Push product_ids qua XCom cho task tiếp theo
    context["ti"].xcom_push(key="product_ids", value=product_ids)
    conn.close()
    return len(product_ids)


# ------------------------------------------------------------------ #
# Task 2: crawl_reviews
# ------------------------------------------------------------------ #

def task_crawl_reviews(**context):
    import sys
    sys.path.insert(0, "/opt/airflow")
    from crawlers import ReviewCrawler

    # Pull product_ids từ XCom của task trước
    product_ids = context["ti"].xcom_pull(
        task_ids="crawl_products", key="product_ids"
    )
    if not product_ids:
        raise ValueError("No product_ids received from crawl_products task")

    logger.info(f"Crawling reviews for {len(product_ids)} products...")
    conn = get_db_conn()
    crawler = ReviewCrawler(db_conn=conn, delay_min=2.0, delay_max=5.0)
    user_ids = crawler.crawl_products(product_ids)

    logger.info(f"Collected {len(user_ids)} unique user_ids from reviews")

    # Push user_ids qua XCom cho task tiếp theo
    context["ti"].xcom_push(key="user_ids", value=user_ids)
    conn.close()
    return len(user_ids)


# ------------------------------------------------------------------ #
# Task 3: crawl_users
# ------------------------------------------------------------------ #

def task_crawl_users(**context):
    import sys
    sys.path.insert(0, "/opt/airflow")
    from crawlers import UserCrawler

    # Pull user_ids từ XCom của task trước
    user_ids = context["ti"].xcom_pull(
        task_ids="crawl_reviews", key="user_ids"
    )
    if not user_ids:
        logger.warning("No user_ids received — skipping user crawl")
        return 0

    logger.info(f"Crawling profiles for {len(user_ids)} users...")
    conn = get_db_conn()
    crawler = UserCrawler(db_conn=conn, delay_min=1.5, delay_max=3.5)
    saved = crawler.crawl_users(user_ids)

    conn.close()
    logger.info(f"Saved {saved} new user profiles")
    return saved


# ------------------------------------------------------------------ #
# Task 4: data_quality_check
# ------------------------------------------------------------------ #

def task_data_quality_check(**context):
    conn = get_db_conn()
    cursor = conn.cursor()
    report = {}

    # 1. Tổng số bản ghi
    for table in ("raw_products", "raw_reviews", "raw_users"):
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        report[f"total_{table}"] = cursor.fetchone()[0]

    # 2. Duplicate reviews (cùng review_id)
    cursor.execute("""
        SELECT COUNT(*) FROM (
            SELECT review_id FROM raw_reviews
            GROUP BY review_id HAVING COUNT(*) > 1
        ) t
    """)
    report["duplicate_reviews"] = cursor.fetchone()[0]

    # 3. Reviews có content null/rỗng
    cursor.execute("""
        SELECT COUNT(*) FROM raw_reviews
        WHERE content IS NULL OR TRIM(content) = ''
    """)
    report["null_content_reviews"] = cursor.fetchone()[0]

    # 4. Reviews crawled trong 24h vừa qua
    cursor.execute("""
        SELECT COUNT(*) FROM raw_reviews
        WHERE crawled_at >= NOW() - INTERVAL '24 hours'
    """)
    report["reviews_last_24h"] = cursor.fetchone()[0]

    # 5. Tỉ lệ reviews có user_id hợp lệ
    cursor.execute("""
        SELECT
            COUNT(*) FILTER (WHERE user_id IS NOT NULL) * 100.0 / NULLIF(COUNT(*), 0)
        FROM raw_reviews
    """)
    report["pct_reviews_with_user"] = round(cursor.fetchone()[0] or 0, 2)

    # ------------------------------------------------------------------ #
    # Log kết quả + cảnh báo
    # ------------------------------------------------------------------ #
    logger.info("=== DATA QUALITY REPORT ===")
    for key, val in report.items():
        logger.info(f"  {key}: {val}")

    # Cảnh báo nếu có vấn đề
    warnings = []

    if report["duplicate_reviews"] > 0:
        warnings.append(f"Found {report['duplicate_reviews']} duplicate reviews!")

    null_pct = report["null_content_reviews"] / max(report["total_raw_reviews"], 1) * 100
    if null_pct > 10:
        warnings.append(f"High null content rate: {null_pct:.1f}%")

    if report["reviews_last_24h"] == 0:
        warnings.append("WARNING: No new reviews crawled in last 24 hours!")

    if report["total_raw_reviews"] < 1000:
        warnings.append(f"Total reviews low: {report['total_raw_reviews']} (target: 30,000+)")

    if warnings:
        logger.warning("=== QUALITY WARNINGS ===")
        for w in warnings:
            logger.warning(f"  {w}")
    else:
        logger.info("All quality checks passed!")

    conn.close()
    return report


# ------------------------------------------------------------------ #
# Khai báo tasks
# ------------------------------------------------------------------ #

t1_crawl_products = PythonOperator(
    task_id="crawl_products",
    python_callable=task_crawl_products,
    dag=dag,
)

t2_crawl_reviews = PythonOperator(
    task_id="crawl_reviews",
    python_callable=task_crawl_reviews,
    dag=dag,
)

t3_crawl_users = PythonOperator(
    task_id="crawl_users",
    python_callable=task_crawl_users,
    dag=dag,
)

t4_quality_check = PythonOperator(
    task_id="data_quality_check",
    python_callable=task_data_quality_check,
    dag=dag,
)

# ------------------------------------------------------------------ #
# Thứ tự thực hiện
# ------------------------------------------------------------------ #

t1_crawl_products >> t2_crawl_reviews >> t3_crawl_users >> t4_quality_check