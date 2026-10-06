-- Тестовая БД проекта: pytest работает только с ней (drop_all/create_all).
SELECT 'CREATE DATABASE erp_lite_test OWNER erp_lite'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'erp_lite_test')\gexec
