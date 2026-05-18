USE campus_ai;

-- 为容器生命周期资源汇总扩展 log 表。
-- 说明：
-- 1. 每个 pod_name 维护一条汇总记录；定时任务 update running 记录，删除容器时最后 update 并标记 deleted。
-- 2. CPU/网络为 counter 增量累加；内存为时间加权平均、峰值和 GB-hours。
-- 3. metrics_complete=false 表示 Prometheus retention 不足或曾出现统计窗口缺口。

ALTER TABLE `log`
  ADD COLUMN app_name VARCHAR(64) NULL AFTER pod_name,
  ADD COLUMN owner_username VARCHAR(255) NULL AFTER user_name,
  ADD COLUMN owner_email VARCHAR(255) NULL AFTER owner_username,
  ADD COLUMN image TEXT NULL AFTER owner_email,
  ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'running' AFTER image,
  MODIFY COLUMN deleted_at TIMESTAMP NULL DEFAULT NULL,
  ADD COLUMN cpu_limit_cores DOUBLE NULL AFTER deleted_at,
  ADD COLUMN memory_limit_bytes BIGINT UNSIGNED NULL AFTER cpu_limit_cores,
  ADD COLUMN cpu_core_seconds DOUBLE NOT NULL DEFAULT 0 AFTER memory_limit_bytes,
  ADD COLUMN cpu_avg_cores DOUBLE NOT NULL DEFAULT 0 AFTER cpu_core_seconds,
  ADD COLUMN cpu_max_cores DOUBLE NOT NULL DEFAULT 0 AFTER cpu_avg_cores,
  ADD COLUMN memory_avg_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0 AFTER cpu_max_cores,
  ADD COLUMN memory_max_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0 AFTER memory_avg_bytes,
  ADD COLUMN memory_byte_seconds DOUBLE NOT NULL DEFAULT 0 AFTER memory_max_bytes,
  ADD COLUMN memory_gb_hours DOUBLE NOT NULL DEFAULT 0 AFTER memory_byte_seconds,
  ADD COLUMN network_rx_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0 AFTER memory_gb_hours,
  ADD COLUMN network_tx_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0 AFTER network_rx_bytes,
  ADD COLUMN metrics_first_collected_at DATETIME NULL AFTER network_tx_bytes,
  ADD COLUMN metrics_last_collected_at DATETIME NULL AFTER metrics_first_collected_at,
  ADD COLUMN metrics_window_count INT NOT NULL DEFAULT 0 AFTER metrics_last_collected_at,
  ADD COLUMN metrics_collected_seconds INT NOT NULL DEFAULT 0 AFTER metrics_window_count,
  ADD COLUMN metrics_complete BOOLEAN NOT NULL DEFAULT TRUE AFTER metrics_collected_seconds,
  ADD COLUMN updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER metrics_complete,
  ADD KEY idx_log_status (status);
