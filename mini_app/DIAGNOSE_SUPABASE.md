# 🔍 Диагностика проблемы подключения Mini App к Supabase

## Проблема
Telegram бот успешно работает с Supabase, но Mini App не может получить данные.

## Основные причины

### 1. Неправильный формат API ключа

**Supabase использует JWT токены**, которые выглядят так:
```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB5cmtudHdlcnZicnVyc25leW5kIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE5MzI1NDksImV4cCI6MjA3NzUwODU0OX0.D1pSh-60JmROW6zh7g_kjnH1tDuYxWOC0DiSfo3oR4o
```

**НЕ используйте ключи вида:**
- `sb_publishable_...` ❌
- `sb_secret_...` ❌

Эти ключи из других систем (например, Stripe) и не подходят для Supabase.

## Как найти правильный ключ

### Шаг 1: Откройте Supabase Dashboard
1. Зайдите на [app.supabase.com](https://app.supabase.com)
2. Выберите ваш проект
3. Перейдите в **Settings** → **API**

### Шаг 2: Найдите правильные ключи

В разделе **API Settings** вы увидите:

1. **Project URL** - это ваш `SUPABASE_URL`
   ```
   https://pyrkntwervbrursneynd.supabase.co
   ```

2. **anon public** ключ - это ваш `SUPABASE_KEY` для Mini App
   ```
   eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   ```
   Это длинный JWT токен, начинающийся с `eyJ...`

3. **service_role** ключ (секретный) - только для сервера
   ⚠️ **НИКОГДА не используйте его в клиентском коде!**

### Шаг 3: Обновите файлы

#### 1. Обновите `.env` на сервере:
```env
SUPABASE_URL=https://pyrkntwervbrursneynd.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9... (anon public ключ)
```

#### 2. Обновите `mini_app/app.js`:
Замените `DEFAULT_SUPABASE_KEY` на ваш `anon public` ключ из Supabase Dashboard.

### Шаг 4: Настройте Row Level Security (RLS)

Если Mini App все еще не работает после обновления ключа:

#### Вариант A: Временно отключить RLS (для тестирования)

Выполните SQL миграцию `supabase/migrations/004_enable_anon_access.sql`:

1. Откройте Supabase Dashboard → **SQL Editor**
2. Скопируйте содержимое файла `supabase/migrations/004_enable_anon_access.sql`
3. Вставьте и выполните (Run)

#### Вариант B: Настроить политики RLS (рекомендуется для production)

Создайте политики, которые разрешают анонимный доступ:

```sql
-- Политика для чтения чатов пользователя
CREATE POLICY "Allow users to read own chats"
ON chats FOR SELECT
USING (true);

-- Политика для создания чатов
CREATE POLICY "Allow users to create chats"
ON chats FOR INSERT
WITH CHECK (true);

-- Политика для обновления чатов
CREATE POLICY "Allow users to update own chats"
ON chats FOR UPDATE
USING (true);

-- Политика для удаления чатов
CREATE POLICY "Allow users to delete own chats"
ON chats FOR DELETE
USING (true);
```

Аналогично для таблиц `messages` и `users`.

### Шаг 5: Настройте CORS

1. В Supabase Dashboard → **Settings** → **API**
2. Найдите раздел **CORS** или **Allowed Origins**
3. Добавьте:
   - `https://*.netlify.app` (если используете Netlify)
   - `https://*.telegram.org`
   - Ваш конкретный домен Mini App

## Проверка работы

1. **Откройте Mini App в Telegram**
2. **Откройте консоль браузера (F12)** → вкладка **Console**
3. **Проверьте логи:**
   - ✅ `Supabase клиент инициализирован` - хорошо
   - ✅ `Тестовый запрос успешен!` - отлично, подключение работает
   - ❌ `Failed to fetch` - проблема с CORS или сетью
   - ❌ `401 Unauthorized` - неправильный ключ
   - ❌ `404 not found` - таблица не найдена или RLS блокирует

## Что проверить в консоли

После обновления кода, откройте консоль и проверьте:

1. **Формат ключа:**
   ```
   Key формат: eyJhbGciOiJIUzI1NiIsInR...
   Key длина: ~200+ символов
   ```
   Если ключ короткий (менее 100 символов) или начинается с `sb_`, он неправильный.

2. **Тестовый запрос:**
   ```
   ✅ Тестовый запрос успешен! Получено записей: X
   ```
   Это означает, что подключение работает.

3. **Ошибки:**
   - Если видите `401`, ключ неправильный
   - Если видите `Failed to fetch`, проблема с CORS
   - Если видите `404` или ошибки RLS, нужно настроить политики безопасности

## Резюме

1. ✅ Убедитесь, что используете **anon public** JWT токен (не `sb_publishable_...`)
2. ✅ Проверьте, что ключ обновлен в `.env` и в `mini_app/app.js`
3. ✅ Выполните SQL миграцию для отключения/настройки RLS
4. ✅ Настройте CORS в Supabase Dashboard
5. ✅ Перезапустите бота после обновления `.env`
6. ✅ Обновите Mini App в Telegram (закройте и откройте снова)

