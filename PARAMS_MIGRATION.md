# 🔧 Миграция для параметров пользователя и исправление ошибок

## Проблемы, которые нужно решить

1. ❌ Ошибка: `Could not find the 'model_name' column` - нужно выполнить миграцию 002
2. ❌ FFmpeg не найден - нужно указать правильный путь
3. ✅ Добавлена система параметров пользователя

## Шаг 1: Выполнение миграций в Supabase

### Миграция 002 (для model_name)
1. Откройте Supabase Dashboard → SQL Editor
2. Скопируйте и выполните SQL из `supabase/migrations/002_add_user_model.sql`

```sql
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS model_name TEXT DEFAULT 'flash';

CREATE INDEX IF NOT EXISTS idx_users_model_name ON users(model_name);
```

### Миграция 003 (для параметров)
3. Выполните SQL из `supabase/migrations/003_add_user_parameters.sql`

```sql
CREATE TABLE IF NOT EXISTS user_parameters (
    parameter_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    parameter_key TEXT NOT NULL,
    parameter_value TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, parameter_key)
);
```

## Шаг 2: Настройка пути к FFmpeg

Система автоматически проверит следующие пути в корне проекта:
- `./ffmpeg/bin/ffmpeg.exe`
- `./ffmpeg/ffmpeg.exe`
- `./ffmpeg.exe`
- `./ffmpeg-8.0/bin/ffmpeg.exe`
- `./ffmpeg-8.0/ffmpeg.exe`

**Если FFmpeg в другой папке**, добавьте в `.env`:
```env
FFMPEG_PATH=C:\code\TG-AI\ваша_папка\ffmpeg.exe
```

**Примечание:** В вашем проекте есть папка `ffmpeg-8.0`, но там только исходники. 
Если у вас есть скомпилированный `ffmpeg.exe`, поместите его в корень проекта или укажите путь в `.env`.

## Шаг 3: Использование параметров

### Команда `/params`
Используйте команду `/params` для управления параметрами:
- Просмотр текущих параметров
- Добавление новых параметров
- Редактирование существующих
- Удаление параметров
- Очистка всех параметров

### Популярные параметры
Система предлагает быстрый доступ к:
- **religion** - Верующий/Верующая
- **age** - Возраст
- **interests** - Интересы
- **language** - Язык общения

### Использование параметров в контексте
Все параметры пользователя автоматически добавляются в контекст каждого запроса к AI, что позволяет боту учитывать персональные настройки пользователя.

## Проверка работы

1. Выполните миграции в Supabase
2. Перезапустите бота
3. Попробуйте команду `/params`
4. Добавьте параметр (например, `religion: верующий`)
5. Отправьте сообщение боту - параметр будет учтен в контексте

