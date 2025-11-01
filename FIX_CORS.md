# 🔧 Исправление ошибки CORS в Mini App

## Проблема
Mini App показывает ошибку "Не удалось подключиться к Supabase" или "Failed to fetch".

## Причина
Скорее всего проблема в Row Level Security (RLS) политиках в Supabase, которые блокируют анонимный доступ к таблицам.

## Решение

### Шаг 1: Выполните SQL миграцию

1. Откройте [Supabase Dashboard](https://app.supabase.com)
2. Выберите ваш проект
3. Перейдите в **SQL Editor**
4. Скопируйте и выполните SQL из файла `supabase/migrations/004_enable_anon_access.sql`

### Шаг 2: Или временно отключите RLS (для теста)

Выполните в SQL Editor:

```sql
-- Временно отключить RLS для тестирования
ALTER TABLE chats DISABLE ROW LEVEL SECURITY;
ALTER TABLE messages DISABLE ROW LEVEL SECURITY;

-- Проверьте что таблицы доступны
SELECT * FROM chats LIMIT 1;
```

**⚠️ ВАЖНО:** После проверки работы Mini App **обязательно включите RLS обратно** и создайте правильные политики!

### Шаг 3: Включить RLS обратно с правильными политиками

После проверки работы:

```sql
-- Включить RLS обратно
ALTER TABLE chats ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

-- Создать политику для анонимного доступа к своим данным
CREATE POLICY "Allow anon access to own chats" ON chats
    FOR ALL
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Allow anon access to own messages" ON messages
    FOR ALL
    USING (true)
    WITH CHECK (true);
```

### Альтернатива: Использовать Service Role Key (НЕ рекомендуется для Mini App)

Если ничего не помогает, можно использовать Service Role Key вместо Anon Key, но это **небезопасно** и не рекомендуется, так как даст полный доступ к БД.

## Проверка

После выполнения миграции:

1. Перезагрузите Mini App в Telegram
2. Откройте консоль браузера (если возможно)
3. Проверьте, что запросы к Supabase проходят успешно

## Дополнительная информация

См. файл `mini_app/CORS_SETUP.md` для более подробной информации о настройке CORS.

