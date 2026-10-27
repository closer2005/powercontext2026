-- 首次启动 seekdb 时执行（docker-compose.yml 通过 INIT_SCRIPTS_PATH 挂载）。
-- 应用默认连接 test 库；这里确保它存在。
CREATE DATABASE IF NOT EXISTS test;