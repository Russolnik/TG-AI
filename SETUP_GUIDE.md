# 📖 Подробное Руководство по Настройке

Этот документ содержит пошаговые инструкции по настройке всех компонентов проекта.

## Шаг 1: Подготовка окружения

### Python 3.10+

Проверьте версию Python:
```bash
python --version
```

Если версия ниже 3.10, обновите Python.

### Установка зависимостей

```bash
pip install -r requirements.txt
```

**Важно:** Для обработки аудио требуется FFmpeg. См. инструкции выше в README.

## Шаг 2: Настройка Telegram Bot

1. Откройте Telegram и найдите [@BotFather](https://t.me/BotFather)
2. Отправьте команду `/newbot`
3. Выберите имя и username для бота
4. Сохраните полученный **Bot Token**
5. (Опционально) Настройте описание и картинку бота

## Шаг 3: Настройка Supabase

### 3.1. Создание проекта

1. Зарегистрируйтесь на [supabase.com](https://supabase.com)
2. Создайте новый проект
3. Дождитесь завершения инициализации (5-10 минут)

### 3.2. Получение credentials

1. В Supabase Dashboard перейдите в **Settings** → **API**
2. Скопируйте:
   - **Project URL** → это ваш `SUPABASE_URL`
   - **anon public** ключ → это ваш `SUPABASE_KEY`

### 3.3. Создание таблиц

1. Перейдите в **SQL Editor**
2. Откройте файл `supabase/migrations/001_initial_schema.sql`
3. Скопируйте весь SQL код
4. Вставьте в SQL Editor и нажмите **Run**
5. Убедитесь, что все таблицы созданы:
   - `api_keys`
   - `users`
   - `chats`
   - `messages`

### 3.4. Настройка Row Level Security (RLS)

Для безопасности рекомендуется настроить RLS политики:

```sql
-- Политика для чтения собственных данных пользователя
CREATE POLICY "Users can read own data"
ON users FOR SELECT
USING (telegram_id::text = current_setting('app.current_user_id', true));

-- Аналогично для chats и messages
-- (это упрощенный пример, настройте под свои нужды)
```

**Примечание:** Для MVP можно временно отключить RLS, но для продакшена обязательно включите.

## Шаг 4: Получение Gemini API ключей

1. Зарегистрируйтесь на [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Создайте API ключи (можно создать до 20 ключей)
3. Скопируйте все ключи

**Важно:**
- Каждый ключ имеет свои лимиты запросов
- Рекомендуется иметь 10-20 ключей для ротации
- Храните ключи в безопасности

## Шаг 5: Настройка .env файла

Создайте файл `.env` в корне проекта:

```env
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
SUPABASE_URL=https://xxxxxxxxxxxxx.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
GEMINI_API_KEYS=key1,key2,key3,key4,key5,key6,key7,key8,key9,key10
MAX_USERS_PER_KEY=5
CONTEXT_WINDOW_SIZE=20
MINI_APP_URL=https://your-app.netlify.app
```

**Формат GEMINI_API_KEYS:** все ключи через запятую, без пробелов.

## Шаг 6: Тестовый запуск бота

1. Запустите бота:
```bash
python bot.py
```

2. Откройте Telegram и найдите вашего бота
3. Отправьте команду `/start`
4. Проверьте, что бот ответил

Если все работает, переходите к следующему шагу.

## Шаг 7: Настройка Mini App

### 7.1. Редактирование app.js

Откройте `mini_app/app.js` и замените:

```javascript
const SUPABASE_URL = 'YOUR_SUPABASE_URL';
const SUPABASE_ANON_KEY = 'YOUR_SUPABASE_ANON_KEY';
```

На ваши реальные значения из Supabase.

### 7.2. Локальное тестирование (опционально)

1. Установите простой HTTP сервер:
```bash
# Python 3
cd mini_app
python -m http.server 8000
```

2. Откройте `http://localhost:8000` в браузере
3. Проверьте консоль на ошибки

### 7.3. Деплой на Netlify

#### Вариант 1: Через веб-интерфейс

1. Зарегистрируйтесь на [netlify.com](https://netlify.com)
2. Перейдите в **Sites** → **Add new site** → **Deploy manually**
3. Перетащите папку `mini_app` в окно браузера
4. Дождитесь завершения деплоя
5. Скопируйте URL (например, `https://random-name-123.netlify.app`)

#### Вариант 2: Через Netlify CLI

```bash
npm install -g netlify-cli
cd mini_app
netlify deploy --prod
```

### 7.4. Обновление .env

Добавьте URL вашего Mini App в `.env`:

```env
MINI_APP_URL=https://your-app.netlify.app
```

### 7.5. Настройка бота для Mini App

1. Перезапустите бота (он автоматически добавит кнопку Mini App)
2. Проверьте, что кнопка "Мои Диалоги" работает

## Шаг 8: Проверка всех функций

Протестируйте каждый функционал:

- ✅ `/start` - регистрация
- ✅ Текстовое сообщение - ответ от AI
- ✅ Голосовое сообщение - транскрибация и ответ
- ✅ Фото - анализ изображения
- ✅ PDF файл - обработка документа
- ✅ Текстовый файл - обработка
- ✅ Аудио файл - транскрибация
- ✅ Mini App - создание/удаление/переименование чатов

## Шаг 9: Продакшен (опционально)

### Хостинг бота

Для 24/7 работы бота используйте:

- **VPS** (DigitalOcean, Hetzner, AWS EC2)
- **Heroku** (если используете бесплатный тариф, учтите ограничения)
- **Railway** или **Render**

### Использование Webhook вместо Polling

Для продакшена рекомендуется использовать webhook:

```python
# Пример настройки webhook
from telegram.ext import Application

application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

# Установка webhook
await application.bot.set_webhook(url="https://your-domain.com/webhook")

# Обработка webhook запросов (используйте FastAPI, Flask и т.д.)
```

### Мониторинг

Настройте логирование и мониторинг:
- Используйте `logging` для записи ошибок
- Настройте уведомления об ошибках (Telegram, email)
- Мониторьте использование API-ключей

## Частые проблемы

### Бот не отвечает
- Проверьте правильность токена
- Убедитесь, что бот запущен
- Проверьте интернет-соединение

### Ошибки с Supabase
- Проверьте правильность URL и ключа
- Убедитесь, что миграции выполнены
- Проверьте RLS политики

### Whisper не работает
- Убедитесь, что FFmpeg установлен
- Проверьте наличие свободного места (модель весит ~500MB)
- Первый запуск загружает модель - подождите

### Mini App не открывается
- Проверьте URL в `.env`
- Убедитесь, что Supabase credentials в `app.js` правильные
- Проверьте консоль браузера на ошибки

## Дополнительные ресурсы

- [Telegram Bot API Docs](https://core.telegram.org/bots/api)
- [Gemini API Docs](https://ai.google.dev/docs)
- [Supabase Docs](https://supabase.com/docs)
- [Telegram Mini Apps Docs](https://core.telegram.org/bots/webapps)

