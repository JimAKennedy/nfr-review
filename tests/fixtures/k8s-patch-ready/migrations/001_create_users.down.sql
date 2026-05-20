-- Rollback migration 001: Drop users table

DROP INDEX IF EXISTS idx_users_username;
DROP TABLE IF EXISTS users;
