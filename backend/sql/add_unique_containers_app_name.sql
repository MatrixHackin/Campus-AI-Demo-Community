USE campus_ai;

-- 给已有 containers 表补充 app_name 字段，并通过唯一索引保证应用名全局唯一。
-- MySQL UNIQUE KEY 允许多个 NULL；已有旧记录可先保持 NULL，新的容器申请会写入非空 app_name。
ALTER TABLE containers
  ADD COLUMN app_name VARCHAR(64) NULL AFTER pod_name,
  ADD UNIQUE KEY uk_containers_app_name (app_name);

-- 如果准备同时启用 WebSSH / 原生 SSH，请继续执行 add_ssh_container_fields.sql。
