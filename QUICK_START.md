# ⚡ Быстрый Старт

Это краткая инструкция для быстрого запуска бота. Для детальной настройки см. [SETUP_GUIDE.md](SETUP_GUIDE.md).

## Шаги запуска

### 1. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 2. Установка FFmpeg
- **Windows:** `choco install ffmpeg` или скачайте с [ffmpeg.org](https://ffmpeg.org)
- **Linux:** `sudo apt install ffmpeg`
- **macOS:** `brew install ffmpeg`

### 3. Создание .env файла
Создайте `.env` в корне проекта:
```env
TELEGRAM_BOT_TOKEN=ваш_токен_бота
SUPABASE_URL=https://ваш_проект.supabase.co
SUPABASE_KEY=ваш_anon_ключ
GEMINI_API_KEYS=ключ1,ключ2,ключ3,...
MAX_USERS_PER_KEY=5
CONTEXT_WINDOW_SIZE=20
MINI_APP_URL=https://ваш_мини_апп.netlify.app
```

### 4. Настройка Supabase
1. Создайте проект на [supabase.com](https://supabase.com)
2. В SQL Editor выполните `supabase/migrations/001_initial_schema.sql`
3. Скопируйте URL и ключ в `.env`

### 5. Инициализация ключей (опционально)
```bash
python init_db.py
```

### 6. Настройка Mini App
1. Откройте `mini_app/app.js`
2. Замените `YOUR_SUPABASE_URL` и `YOUR_SUPABASE_ANON_KEY`
3. Загрузите папку `mini_app` на Netlify
4. Добавьте URL в `.env`

### 7. Запуск
```bash
python bot.py
```

## Проверка работы

1. Откройте Telegram и найдите вашего бота
2. Отправьте `/start`
3. Бот должен ответить приветствием
4. Отправьте текстовое сообщение - получите ответ от AI
5. Попробуйте отправить фото, голос, файл

## Что делать если не работает?

- Проверьте все значения в `.env`
- Убедитесь, что миграции Supabase выполнены
- Проверьте логи бота на ошибки
- См. раздел "Решение проблем" в [README.md](README.md)

---

Для подробных инструкций см. [SETUP_GUIDE.md](SETUP_GUIDE.md)

