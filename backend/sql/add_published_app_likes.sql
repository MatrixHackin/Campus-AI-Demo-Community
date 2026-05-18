USE campus_ai;

-- 应用市场点赞功能：
-- 1. published_apps.like_count 作为展示用计数缓存。
-- 2. published_app_likes 记录用户点赞状态，通过唯一索引保证同一用户对同一应用只能点赞一次。
-- 3. 取消发布不主动清理点赞记录；删除容器时会同步清理点赞记录。

ALTER TABLE published_apps
  ADD COLUMN like_count INT NOT NULL DEFAULT 0 AFTER visit_count,
  ADD COLUMN is_published BOOLEAN NOT NULL DEFAULT TRUE AFTER like_count,
  ADD KEY idx_published_apps_is_published (is_published);

CREATE TABLE IF NOT EXISTS published_app_likes (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  publication_id BIGINT UNSIGNED NOT NULL,
  user_key VARCHAR(255) NOT NULL,
  username VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_like_publication_user (publication_id, user_key),
  KEY idx_likes_publication_id (publication_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

UPDATE published_apps app
LEFT JOIN (
  SELECT publication_id, COUNT(*) AS total_likes
  FROM published_app_likes
  GROUP BY publication_id
) likes ON likes.publication_id = app.id
SET app.like_count = COALESCE(likes.total_likes, 0);
