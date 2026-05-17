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
  last_login_at TIMESTAMP NULL DEFAULT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_sso_users_provider_subject (auth_provider, provider_subject),
  KEY idx_sso_users_username (username),
  KEY idx_sso_users_email (email),
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
  owner_id BIGINT UNSIGNED NOT NULL,
  pod_name VARCHAR(255) NOT NULL,
  app_name VARCHAR(255) NOT NULL,
  app_description TEXT NULL,
  cover_url TEXT NOT NULL,
  app_port INT UNSIGNED NOT NULL,
  visit_count INT NOT NULL DEFAULT 0,
  published_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_published_apps_pod_name (pod_name),
  KEY idx_published_apps_owner_id (owner_id),
  KEY idx_published_apps_pod_name (pod_name),
  CONSTRAINT fk_published_apps_owner
    FOREIGN KEY (owner_id) REFERENCES users (id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `log` (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  pod_name VARCHAR(255) NOT NULL,
  namespace VARCHAR(255) NOT NULL,
  gpu_count INT NOT NULL DEFAULT 0,
  start_time DATETIME NULL,
  node_name VARCHAR(255) NULL,
  duration INT NOT NULL DEFAULT 0 COMMENT '运行时长(秒)',
  user_email VARCHAR(255) NULL,
  user_name VARCHAR(255) NULL,
  deleted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_log_pod_name (pod_name),
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
