USE campus_ai;

-- 应用市场发布表迁移：
-- 1. 兼容 SSO 用户：不再依赖 users.id 外键，改用 owner_username/auth_provider。
-- 2. 封面只保存轻量图片 URL，图片文件存储在后端 static/covers，后续可替换为图床/对象存储 URL。
-- 3. 已有旧 published_apps 表如有数据，请先备份再执行。

ALTER TABLE published_apps DROP FOREIGN KEY fk_published_apps_owner;

ALTER TABLE published_apps
  MODIFY COLUMN owner_id BIGINT UNSIGNED NULL,
  MODIFY COLUMN cover_url TEXT NULL,
  MODIFY COLUMN app_port INT UNSIGNED NOT NULL DEFAULT 3000,
  ADD COLUMN app_url TEXT NULL AFTER cover_url,
  ADD COLUMN owner_username VARCHAR(255) NULL AFTER app_port,
  ADD COLUMN owner_display_name VARCHAR(255) NULL AFTER owner_username,
  ADD COLUMN auth_provider VARCHAR(32) NOT NULL DEFAULT 'local' AFTER owner_display_name;

UPDATE published_apps
SET
  app_url = CONCAT('https://gpunion.hkust-gz.edu.cn/apps/', app_name)
WHERE app_url IS NULL OR app_url = '';

UPDATE published_apps
SET owner_username = CONCAT('legacy-user-', owner_id)
WHERE owner_username IS NULL OR owner_username = '';

ALTER TABLE published_apps
  MODIFY COLUMN app_url TEXT NOT NULL,
  MODIFY COLUMN owner_username VARCHAR(255) NOT NULL,
  ADD UNIQUE KEY uk_published_apps_app_name (app_name),
  ADD KEY idx_published_apps_owner_username (owner_username),
  ADD KEY idx_published_apps_published_at (published_at);
