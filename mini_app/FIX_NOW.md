# 🔧 СРОЧНОЕ ИСПРАВЛЕНИЕ: "Failed to fetch"

## Проблема
Ошибка "TypeError: Failed to fetch" означает, что браузер не может подключиться к Supabase.

## Решение (выполните ВСЕ шаги):

### Шаг 1: Отключить RLS (ОБЯЗАТЕЛЬНО!)

1. Откройте [Supabase Dashboard](https://app.supabase.com)
2. Выберите ваш проект
3. Перейдите в **SQL Editor** (в левом меню)
4. Скопируйте ВЕСЬ код из файла `supabase/migrations/004_disable_rls.sql`:

```sql
-- Отключение Row Level Security (RLS) для работы Mini App
ALTER TABLE chats DISABLE ROW LEVEL SECURITY;
ALTER TABLE messages DISABLE ROW LEVEL SECURITY;
ALTER TABLE users DISABLE ROW LEVEL SECURITY;
ALTER TABLE user_parameters DISABLE ROW LEVEL SECURITY;
```

5. Вставьте в SQL Editor
6. Нажмите **Run** или **Execute**
7. Должно появиться сообщение об успехе

### Шаг 2: Настроить CORS

1. В Supabase Dashboard перейдите в **Settings** → **API**
2. Найдите раздел **CORS** или **Allowed Origins**
3. Добавьте следующие домены (каждый с новой строки):
   ```
   https://yourai-bottelegram.netlify.app
   https://*.netlify.app
   https://*.telegram.org
   ```
4. Сохраните изменения

### Шаг 3: Проверить работу

1. **Обновите Mini App** в Telegram (закройте и откройте заново)
2. **Откройте консоль браузера** (F12) в Mini App
3. Проверьте логи:
   - Должно быть: `✅ Supabase клиент инициализирован`
   - Должно быть: `✅ Загружено чатов: X` (где X - количество ваших чатов)
   - Если есть ошибка, скопируйте её из консоли

### Шаг 4: Если всё ещё не работает

Откройте консоль (F12) и скопируйте ВСЕ логи, которые начинаются с:
- `📤 Запрос к Supabase:`
- `📥 Ответ от Supabase:`
- `❌ Ошибка`

Пришлите эти логи для дальнейшей диагностики.

## Важно!

- Миграцию SQL нужно выполнить **ОДИН РАЗ**
- После выполнения миграции всё должно заработать
- Если проблема сохраняется после выполнения всех шагов - проблема в сети или в ключах

