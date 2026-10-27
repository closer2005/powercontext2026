-- seekdb 初始化：创建 Dify 运行所需的三个库
-- 在 seekdb 容器内执行：
--   docker exec -i seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PASSWORD" < seekdb_init.sql
CREATE DATABASE IF NOT EXISTS dify;
CREATE DATABASE IF NOT EXISTS dify_plugin;
CREATE DATABASE IF NOT EXISTS dify_vector;
SHOW DATABASES;