-- 应用市场发布审核与责任承诺：
-- 1. 已发布应用默认迁移为 approved，历史下架应用迁移为 unpublished。
-- 2. is_published 继续表示是否在应用市场可见，只有 approved 才应为 1。
-- 3. 管理员审核策略保存在 platform_settings。

CREATE TABLE IF NOT EXISTS platform_settings (
  setting_key VARCHAR(128) NOT NULL,
  setting_value TEXT NOT NULL,
  updated_by VARCHAR(255) NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (setting_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE published_apps
  MODIFY COLUMN published_at TIMESTAMP NULL DEFAULT NULL,
  ADD COLUMN review_status VARCHAR(32) NOT NULL DEFAULT 'approved' AFTER is_published,
  ADD COLUMN submitted_at TIMESTAMP NULL DEFAULT NULL AFTER review_status,
  ADD COLUMN reviewed_at TIMESTAMP NULL DEFAULT NULL AFTER submitted_at,
  ADD COLUMN reviewed_by VARCHAR(255) NULL AFTER reviewed_at,
  ADD COLUMN review_note TEXT NULL AFTER reviewed_by,
  ADD COLUMN reject_reason TEXT NULL AFTER review_note,
  ADD COLUMN responsibility_ack BOOLEAN NOT NULL DEFAULT FALSE AFTER reject_reason,
  ADD COLUMN responsibility_ack_version VARCHAR(32) NULL AFTER responsibility_ack,
  ADD COLUMN responsibility_ack_at TIMESTAMP NULL DEFAULT NULL AFTER responsibility_ack_version,
  ADD COLUMN responsibility_ack_user_key VARCHAR(255) NULL AFTER responsibility_ack_at,
  ADD KEY idx_published_apps_review_status (review_status, submitted_at);

UPDATE published_apps
SET review_status = CASE WHEN is_published = 1 THEN 'approved' ELSE 'unpublished' END,
    submitted_at = COALESCE(submitted_at, published_at, updated_at),
    reviewed_at = CASE WHEN is_published = 1 THEN COALESCE(reviewed_at, published_at, updated_at) ELSE reviewed_at END,
    reviewed_by = CASE WHEN is_published = 1 THEN COALESCE(reviewed_by, 'system') ELSE reviewed_by END,
    responsibility_ack = CASE WHEN is_published = 1 THEN 1 ELSE responsibility_ack END,
    responsibility_ack_version = COALESCE(responsibility_ack_version, 'legacy'),
    responsibility_ack_at = CASE WHEN is_published = 1 THEN COALESCE(responsibility_ack_at, published_at, updated_at) ELSE responsibility_ack_at END
WHERE review_status IN ('approved', 'unpublished');

INSERT INTO platform_settings (setting_key, setting_value, updated_by)
VALUES
  ('app_publish_review_policy', 'no_review', 'migration'),
  ('responsibility_ack_version', '2026-05-31', 'migration')
ON DUPLICATE KEY UPDATE
  setting_value = setting_value;
