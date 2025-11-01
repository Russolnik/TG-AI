-- Отключение Row Level Security (RLS) для работы Mini App
-- ВНИМАНИЕ: Это временная мера для тестирования.
-- Для production нужно настроить правильные политики RLS.

-- Отключаем RLS для основных таблиц
ALTER TABLE chats DISABLE ROW LEVEL SECURITY;
ALTER TABLE messages DISABLE ROW LEVEL SECURITY;
ALTER TABLE users DISABLE ROW LEVEL SECURITY;

-- Также для таблицы параметров пользователя (если используется)
ALTER TABLE user_parameters DISABLE ROW LEVEL SECURITY;

-- Для таблицы api_keys лучше оставить RLS включенным для безопасности
-- ALTER TABLE api_keys DISABLE ROW LEVEL SECURITY;

