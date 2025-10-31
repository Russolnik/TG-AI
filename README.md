# Telegram AI Bot с Gemini API

Полнофункциональный Telegram-бот с интеграцией Google Gemini API, управлением диалогами через Supabase и Mini App для управления чатами.

## 🚀 Возможности

- ✅ Текстовый чат с AI (Gemini API)
- ✅ Обработка голосовых сообщений (Speech-to-Text с Whisper)
- ✅ Анализ фотографий (Gemini Vision)
- ✅ Обработка файлов (PDF, TXT, аудио)
- ✅ Управление множеством диалогов
- ✅ Telegram Mini App для управления чатами
- ✅ Умное распределение API-ключей (максимум 5 пользователей на ключ)
- ✅ Автоматическое сжатие контекста для экономии токенов

## 📋 Требования

- Python 3.10+
- Supabase аккаунт
- Telegram Bot Token
- Google Gemini API ключи (10-20 штук)
- FFmpeg (для обработки аудио)

## 🔧 Установка и Настройка

### 1. Клонирование и установка зависимостей

```bash
git clone <repository-url>
cd TG-AI
pip install -r requirements.txt
```

### 2. Установка FFmpeg

**Windows:**
- Скачайте FFmpeg с [официального сайта](https://ffmpeg.org/download.html)
- Добавьте в PATH или установите через chocolatey: `choco install ffmpeg`

**Linux:**
```bash
sudo apt update && sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

### 3. Настройка переменных окружения

Создайте файл `.env` в корне проекта:

```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key_here

# Gemini API Keys (разделены запятыми, минимум 10-20 ключей)
GEMINI_API_KEYS=key1,key2,key3,key4,key5,key6,key7,key8,key9,key10,key11,key12,key13,key14,key15,key16,key17,key18,key19,key20

# Application Configuration
MAX_USERS_PER_KEY=5
CONTEXT_WINDOW_SIZE=20

# Mini App URL (после деплоя на Netlify)
MINI_APP_URL=https://your-app.netlify.app
```

**Как получить Telegram Bot Token:**
1. Напишите [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте команду `/newbot`
3. Следуйте инструкциям и сохраните полученный токен

**Как получить Supabase credentials:**
1. Зарегистрируйтесь на [supabase.com](https://supabase.com)
2. Создайте новый проект
3. Перейдите в Settings → API
4. Скопируйте `Project URL` и `anon public` ключ

### 4. Настройка базы данных Supabase

1. Откройте Supabase Dashboard → SQL Editor
2. Выполните SQL из файла `supabase/migrations/001_initial_schema.sql`
3. Проверьте, что все таблицы созданы успешно

### 5. Добавление API-ключей в базу данных

После выполнения миграции, ключи из `.env` автоматически добавятся в БД при первом запуске бота. Или добавьте их вручную через SQL:

```sql
INSERT INTO api_keys (api_key, is_active) VALUES
('your_gemini_key_1', true),
('your_gemini_key_2', true),
-- ... добавьте все ключи
('your_gemini_key_20', true);
```

### 6. Настройка Telegram Mini App

1. Отредактируйте `mini_app/app.js`:
   - Замените `YOUR_SUPABASE_URL` на ваш Supabase URL
   - Замените `YOUR_SUPABASE_ANON_KEY` на ваш Supabase anon key

2. Разверните на Netlify:
   - Зарегистрируйтесь на [netlify.com](https://netlify.com)
   - Перетащите папку `mini_app` в Netlify или используйте Git
   - Скопируйте URL вашего приложения

3. Обновите `.env`:
   - Добавьте `MINI_APP_URL` с URL вашего Netlify приложения

4. Настройте бота для работы с Mini App:
   - В `.env` укажите правильный `MINI_APP_URL`
   - Перезапустите бота

### 7. Запуск бота

```bash
python bot.py
```

Бот будет работать в режиме polling. Для продакшена рекомендуется использовать webhook.

## 📁 Структура проекта

```
TG-AI/
├── bot.py                 # Основной файл бота
├── database.py            # Работа с Supabase
├── api_key_manager.py     # Логика управления API-ключами
├── gemini_client.py       # Клиент для Gemini API
├── handlers.py            # Обработчики сообщений (голос, фото, файлы)
├── config.py              # Конфигурация
├── .env                   # Переменные окружения (создайте сами)
├── requirements.txt       # Python зависимости
├── supabase/
│   └── migrations/
│       └── 001_initial_schema.sql  # SQL миграции для БД
├── mini_app/              # Telegram Mini App
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── netlify.toml
└── README.md
```

## 🗄️ База данных

Проект использует Supabase для хранения:

- **api_keys** - API-ключи Gemini и их статус
- **users** - Пользователи и их привязка к API-ключам
- **chats** - Чаты (диалоги) пользователей
- **messages** - История сообщений

### Логика распределения ключей

- Каждый API-ключ может обслуживать максимум 5 пользователей
- При регистрации нового пользователя система автоматически находит свободный ключ
- Если все ключи заняты, пользователь получает сообщение о лимите

## 🌐 Telegram Mini App

Mini App позволяет:
- Просматривать все свои чаты
- Создавать новые чаты
- Переименовывать чаты
- Удалять чаты
- Переключаться между активными чатами

### Деплой на Netlify

1. Создайте аккаунт на Netlify
2. Загрузите папку `mini_app` или подключите Git репозиторий
3. Настройте build settings (не требуется, так как это статический сайт)
4. Скопируйте URL и добавьте в `.env`

## 🔒 Безопасность

- Никогда не коммитьте `.env` файл в Git
- Используйте Row Level Security (RLS) в Supabase для защиты данных
- Ограничьте доступ к API-ключам только необходимым пользователям

## 🐛 Решение проблем

**Бот не отвечает:**
- Проверьте правильность `TELEGRAM_BOT_TOKEN`
- Убедитесь, что бот запущен
- Проверьте логи на наличие ошибок

**Ошибки с Supabase:**
- Проверьте правильность `SUPABASE_URL` и `SUPABASE_KEY`
- Убедитесь, что миграции выполнены
- Проверьте настройки RLS политик

**Ошибки обработки голоса/аудио:**
- Убедитесь, что FFmpeg установлен и доступен в PATH
- Проверьте наличие свободного места на диске

**Mini App не работает:**
- Проверьте правильность Supabase credentials в `app.js`
- Убедитесь, что URL указан правильно в `.env`
- Проверьте консоль браузера на наличие ошибок

## 📝 Лицензия

MIT

