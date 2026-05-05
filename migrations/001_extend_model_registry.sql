-- Chạy một lần trên DB đã tồn tại (volume Postgres cũ không chạy lại init-db.sql).
--
-- Từ máy có Docker:
--   docker compose exec -T postgres psql -U airflow -d tiki_data -f - < migrations/001_extend_model_registry.sql
-- (chạy trong thư mục DS, đường dẫn file chỉnh theo máy bạn)

ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS model_name TEXT;
ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS threshold REAL;
ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS metrics_detail JSONB;
ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS metrics_path TEXT;
