USE campus_ai;

-- 让 sso_users 同时承载管理员分配的本地账号。
-- SSO 用户 password_hash 保持 NULL，local_login_enabled 保持 0；
-- 本地账号由管理员预创建，使用 username + password_hash 登录。

ALTER TABLE sso_users
  ADD COLUMN password_hash VARCHAR(255) NULL AFTER emp_id,
  ADD COLUMN local_login_enabled BOOLEAN NOT NULL DEFAULT FALSE AFTER password_hash,
  ADD KEY idx_sso_users_local_login (auth_provider, local_login_enabled, username);
