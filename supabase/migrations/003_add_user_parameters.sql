-- Добавление таблицы для параметров пользователя
CREATE TABLE IF NOT EXISTS user_parameters (
    parameter_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    parameter_key TEXT NOT NULL,
    parameter_value TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, parameter_key)
);

-- Создание индексов
CREATE INDEX IF NOT EXISTS idx_user_parameters_user_id ON user_parameters(user_id);
CREATE INDEX IF NOT EXISTS idx_user_parameters_key ON user_parameters(parameter_key);

-- Функция для обновления updated_at
CREATE TRIGGER update_user_parameters_updated_at
    BEFORE UPDATE ON user_parameters
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

