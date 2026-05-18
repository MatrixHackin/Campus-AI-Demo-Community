USE campus_ai;

-- 应用市场评分与评论：
-- 1. 每个用户对每个应用最多一条评价，可重复提交进行更新。
-- 2. 取消发布不删除评价；删除应用时后端会清理对应评价。
-- 3. published_apps 中缓存评分统计，方便应用市场列表快速展示。

CREATE TABLE IF NOT EXISTS published_app_reviews (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  publication_id BIGINT UNSIGNED NOT NULL,
  user_key VARCHAR(255) NOT NULL,
  username VARCHAR(255) NULL,
  display_name VARCHAR(255) NULL,
  rating TINYINT UNSIGNED NOT NULL,
  comment TEXT NULL,
  is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_review_publication_user (publication_id, user_key),
  KEY idx_reviews_publication_id (publication_id),
  KEY idx_reviews_visible (publication_id, is_deleted, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE published_apps
  ADD COLUMN review_count INT NOT NULL DEFAULT 0 AFTER like_count,
  ADD COLUMN rating_sum INT NOT NULL DEFAULT 0 AFTER review_count,
  ADD COLUMN rating_avg DECIMAL(3,2) NOT NULL DEFAULT 0.00 AFTER rating_sum;

