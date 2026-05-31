CREATE DATABASE IF NOT EXISTS campus_ai
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE campus_ai;

CREATE TABLE IF NOT EXISTS users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL,
  display_name VARCHAR(128) NOT NULL,
  emp_id VARCHAR(128) NULL,
  password_hash VARCHAR(255) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_users_username (username),
  UNIQUE KEY uk_users_emp_id (emp_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sso_users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  auth_provider VARCHAR(32) NOT NULL DEFAULT 'sso',
  provider_subject VARCHAR(128) NOT NULL,
  username VARCHAR(128) NOT NULL,
  display_name VARCHAR(128) NOT NULL,
  user_type VARCHAR(32) NULL COMMENT 'staff, student, project 等 SSO 账号类型',
  email VARCHAR(255) NULL,
  department VARCHAR(128) NULL,
  emp_id VARCHAR(128) NULL,
  password_hash VARCHAR(255) NULL,
  local_login_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  last_login_at TIMESTAMP NULL DEFAULT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_sso_users_provider_subject (auth_provider, provider_subject),
  KEY idx_sso_users_username (username),
  KEY idx_sso_users_email (email),
  KEY idx_sso_users_local_login (auth_provider, local_login_enabled, username),
  UNIQUE KEY uk_sso_users_emp_id (emp_id),
  KEY idx_sso_users_last_login_at (last_login_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS containers (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  pod_name VARCHAR(255) NOT NULL,
  app_name VARCHAR(64) NOT NULL,
  namespace VARCHAR(255) NULL,
  username VARCHAR(255) NOT NULL,
  password VARCHAR(255) NOT NULL,
  ssh_username VARCHAR(255) NULL,
  ssh_service_name VARCHAR(255) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_containers_pod_name (pod_name),
  UNIQUE KEY uk_containers_app_name (app_name),
  KEY idx_containers_pod_name (pod_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS published_apps (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  pod_name VARCHAR(255) NOT NULL,
  app_name VARCHAR(255) NOT NULL,
  app_description TEXT NULL,
  cover_url TEXT NULL,
  app_url TEXT NOT NULL,
  app_port INT UNSIGNED NOT NULL DEFAULT 3000,
  owner_username VARCHAR(255) NOT NULL,
  owner_display_name VARCHAR(255) NULL,
  auth_provider VARCHAR(32) NOT NULL DEFAULT 'local',
  visit_count INT NOT NULL DEFAULT 0,
  like_count INT NOT NULL DEFAULT 0,
  review_count INT NOT NULL DEFAULT 0,
  rating_sum INT NOT NULL DEFAULT 0,
  rating_avg DECIMAL(3,2) NOT NULL DEFAULT 0.00,
  is_published BOOLEAN NOT NULL DEFAULT TRUE,
  review_status VARCHAR(32) NOT NULL DEFAULT 'approved',
  submitted_at TIMESTAMP NULL DEFAULT NULL,
  reviewed_at TIMESTAMP NULL DEFAULT NULL,
  reviewed_by VARCHAR(255) NULL,
  review_note TEXT NULL,
  reject_reason TEXT NULL,
  responsibility_ack BOOLEAN NOT NULL DEFAULT FALSE,
  responsibility_ack_version VARCHAR(32) NULL,
  responsibility_ack_at TIMESTAMP NULL DEFAULT NULL,
  responsibility_ack_user_key VARCHAR(255) NULL,
  published_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_published_apps_pod_name (pod_name),
  UNIQUE KEY uk_published_apps_app_name (app_name),
  KEY idx_published_apps_owner_username (owner_username),
  KEY idx_published_apps_is_published (is_published),
  KEY idx_published_apps_review_status (review_status, submitted_at),
  KEY idx_published_apps_pod_name (pod_name),
  KEY idx_published_apps_published_at (published_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS platform_settings (
  setting_key VARCHAR(128) NOT NULL,
  setting_value TEXT NOT NULL,
  updated_by VARCHAR(255) NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (setting_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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

CREATE TABLE IF NOT EXISTS `log` (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  pod_name VARCHAR(255) NOT NULL,
  app_name VARCHAR(64) NULL,
  namespace VARCHAR(255) NOT NULL,
  gpu_count INT NOT NULL DEFAULT 0,
  start_time DATETIME NULL,
  node_name VARCHAR(255) NULL,
  duration INT NOT NULL DEFAULT 0 COMMENT '运行时长(秒)',
  user_email VARCHAR(255) NULL,
  user_name VARCHAR(255) NULL,
  owner_username VARCHAR(255) NULL,
  owner_email VARCHAR(255) NULL,
  image TEXT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'running',
  deleted_at TIMESTAMP NULL DEFAULT NULL,
  cpu_limit_cores DOUBLE NULL,
  memory_limit_bytes BIGINT UNSIGNED NULL,
  cpu_core_seconds DOUBLE NOT NULL DEFAULT 0,
  cpu_avg_cores DOUBLE NOT NULL DEFAULT 0,
  cpu_max_cores DOUBLE NOT NULL DEFAULT 0,
  memory_avg_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0,
  memory_max_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0,
  memory_byte_seconds DOUBLE NOT NULL DEFAULT 0,
  memory_gb_hours DOUBLE NOT NULL DEFAULT 0,
  network_rx_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0,
  network_tx_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0,
  metrics_first_collected_at DATETIME NULL,
  metrics_last_collected_at DATETIME NULL,
  metrics_window_count INT NOT NULL DEFAULT 0,
  metrics_collected_seconds INT NOT NULL DEFAULT 0,
  metrics_complete BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_log_pod_name (pod_name),
  KEY idx_log_status (status),
  KEY idx_log_user_email (user_email),
  KEY idx_log_deleted_at (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO users (username, display_name, password_hash)
VALUES (
  'admin',
  '管理员',
  'pbkdf2_sha256$260000$campusai_admin_2026$2a4036c74f768273524d9bb6b3d51d3aca7a091712558ceb496ad4c594d5a86e'
) ON DUPLICATE KEY UPDATE
  display_name = VALUES(display_name),
  password_hash = VALUES(password_hash);
