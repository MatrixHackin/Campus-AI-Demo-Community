USE campus_ai;

-- 为 WebSSH / 原生 SSH 网关补充容器路由信息。
-- 已有记录允许 NULL；新申请容器会写入 namespace、ssh_username、ssh_service_name。
ALTER TABLE containers
  ADD COLUMN namespace VARCHAR(255) NULL AFTER app_name,
  ADD COLUMN ssh_username VARCHAR(255) NULL AFTER password,
  ADD COLUMN ssh_service_name VARCHAR(255) NULL AFTER ssh_username;
