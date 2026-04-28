import logging
import psycopg2
from datetime import datetime
from .base_crawler import BaseCrawler

logger = logging.getLogger(__name__)

USER_URL = "https://tiki.vn/api/v2/users/{user_id}"


class UserCrawler(BaseCrawler):
    """
    Crawl thông tin user từ danh sách user_ids.
    Skip user đã có trong DB để tiết kiệm requests.
    """

    def __init__(self, db_conn: psycopg2.extensions.connection, **kwargs):
        super().__init__(checkpoint_path="checkpoints/users.json", **kwargs)
        self.conn = db_conn
        self.cursor = db_conn.cursor()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def crawl_users(self, user_ids: list[int]) -> int:
        """
        Crawl profile cho danh sách user_ids.
        Trả về số user đã lưu thành công.
        """
        unique_ids = list(set(filter(None, user_ids)))
        existing_ids = self._get_existing_user_ids(unique_ids)
        new_ids = [uid for uid in unique_ids if uid not in existing_ids]

        logger.info(
            f"Total user_ids: {len(unique_ids)} | "
            f"Already in DB: {len(existing_ids)} | "
            f"To crawl: {len(new_ids)}"
        )

        done_users = set(self.checkpoint.get("done_users", []))
        saved_count = 0

        for i, user_id in enumerate(new_ids, 1):
            if user_id in done_users:
                continue

            data = self.get(USER_URL.format(user_id=user_id))
            if data:
                ok = self._save_user(data)
                if ok:
                    saved_count += 1
                    self.conn.commit()

            done_users.add(user_id)
            if i % 50 == 0:
                self.save_checkpoint({"done_users": list(done_users)})
                logger.info(f"  Progress: {i}/{len(new_ids)} users | Saved: {saved_count}")

        self.save_checkpoint({"done_users": list(done_users)})
        logger.info(f"UserCrawler done. Saved {saved_count} new users.")
        return saved_count

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _save_user(self, data: dict) -> bool:
        user_id = data.get("id")
        if not user_id:
            return False

        sql = """
            INSERT INTO raw_users (
                user_id, name, full_name, avatar_url,
                total_review, join_time, crawled_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                total_review = EXCLUDED.total_review,
                crawled_at   = EXCLUDED.crawled_at
        """
        try:
            self.cursor.execute(sql, (
                user_id,
                data.get("name"),
                data.get("full_name"),
                data.get("avatar_url"),
                data.get("total_review", 0),
                data.get("join_time"),
                datetime.utcnow(),
            ))
            return True
        except Exception as e:
            logger.error(f"DB error saving user {user_id}: {e}")
            self.conn.rollback()
            return False

    def _get_existing_user_ids(self, user_ids: list[int]) -> set[int]:
        if not user_ids:
            return set()
        self.cursor.execute(
            "SELECT user_id FROM raw_users WHERE user_id = ANY(%s)",
            (user_ids,)
        )
        return {row[0] for row in self.cursor.fetchall()}