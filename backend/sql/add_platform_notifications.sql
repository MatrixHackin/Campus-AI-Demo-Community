-- 平台消息中心：
-- 1. platform_notifications 保存消息主体，全员公告只保存一条。
-- 2. platform_notification_receipts 保存用户已读/关闭状态，按需写入。

CREATE TABLE IF NOT EXISTS platform_notifications (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  title VARCHAR(120) NOT NULL,
  content TEXT NOT NULL,
  notification_type VARCHAR(64) NOT NULL DEFAULT 'system_announcement',
  scope VARCHAR(16) NOT NULL DEFAULT 'all',
  recipient_username VARCHAR(255) NULL,
  sender_username VARCHAR(255) NULL,
  related_type VARCHAR(64) NULL,
  related_id BIGINT UNSIGNED NULL,
  expires_at TIMESTAMP NULL DEFAULT NULL,
  is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_platform_notifications_scope (scope, recipient_username, created_at),
  KEY idx_platform_notifications_type (notification_type, created_at),
  KEY idx_platform_notifications_visible (is_deleted, expires_at, created_at),
  KEY idx_platform_notifications_related (related_type, related_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS platform_notification_receipts (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  notification_id BIGINT UNSIGNED NOT NULL,
  recipient_username VARCHAR(255) NOT NULL,
  read_at TIMESTAMP NULL DEFAULT NULL,
  dismissed_at TIMESTAMP NULL DEFAULT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_notification_receipt_user (notification_id, recipient_username),
  KEY idx_notification_receipts_user_read (recipient_username, read_at, dismissed_at),
  KEY idx_notification_receipts_notification_id (notification_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
