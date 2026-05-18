-- Migration 002: Add email column to users

ALTER TABLE users ADD COLUMN email VARCHAR(255);
CREATE UNIQUE INDEX idx_users_email ON users (email);
