-- 002_canonicalize_review_ids.sql — chuẩn hóa review_id trong Neon (backup trước khi chạy).
-- Mục đích: các bản import CSV/Excel thường lưu số kiểu 12345.0 text; crawler/API lại lưu 12345 → join incremental fail.
--
-- Bước 1 — kiểm tra trùng sau khi chuẩn hóa (phải trả 0 dòng mới an toàn UPDATE):
-- SELECT c, COUNT(*) FROM (
--   SELECT regexp_replace(btrim(review_id::text), '\.0+$', '') AS c FROM raw_reviews
-- ) t GROUP BY c HAVING COUNT(*) > 1;
--
-- Bước 2 — nếu không trùng, chạy (hoặc chỉ chạy trên bảng cần):

BEGIN;

UPDATE raw_reviews
SET review_id = regexp_replace(btrim(review_id::text), '\.0+$', '')
WHERE review_id IS DISTINCT FROM regexp_replace(btrim(review_id::text), '\.0+$', '');

UPDATE processed_reviews
SET review_id = regexp_replace(btrim(review_id::text), '\.0+$', '')
WHERE review_id IS DISTINCT FROM regexp_replace(btrim(review_id::text), '\.0+$', '');

COMMIT;
