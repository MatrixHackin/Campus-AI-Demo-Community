USE campus_ai;

-- 给已有 sso_users 表补充 emp_id 唯一约束。
-- 执行前请先确认不存在重复的非空 emp_id；MySQL UNIQUE KEY 允许多个 NULL。
ALTER TABLE sso_users
  DROP INDEX idx_sso_users_emp_id,
  ADD UNIQUE KEY uk_sso_users_emp_id (emp_id);

-- 给普通本地 users 表补充 emp_id 字段和唯一约束。
-- MySQL UNIQUE KEY 允许多个 NULL。
ALTER TABLE users
  ADD COLUMN emp_id VARCHAR(128) NULL AFTER display_name,
  ADD UNIQUE KEY uk_users_emp_id (emp_id);
