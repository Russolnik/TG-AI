-- Добавление поля для выбранной модели пользователя
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS model_name TEXT DEFAULT 'flash';

-- Создание индекса для поля модели (опционально)
CREATE INDEX IF NOT EXISTS idx_users_model_name ON users(model_name);

