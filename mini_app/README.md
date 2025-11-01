# Mini App для управления диалогами

## Локальная разработка

### 1. Запуск локального сервера

```bash
cd mini_app
python server.py
```

Сервер запустится на `http://localhost:8000`

### 2. Настройка ngrok для доступа из Telegram

```bash
ngrok http 8000
```

Или используйте любой другой туннелинг сервис (Cloudflare Tunnel, локальный IP и т.д.)

### 3. Настройка в боте

Обновите `MINI_APP_URL` в `.env`:
```
MINI_APP_URL=https://your-ngrok-url.ngrok.io
```

### 4. Настройка Supabase в Mini App

В файле `app.js` замените:
- `YOUR_SUPABASE_URL` на ваш Supabase URL
- `YOUR_SUPABASE_ANON_KEY` на ваш Supabase Anon Key

Или используйте localStorage для конфигурации:
```javascript
localStorage.setItem('supabase_config', JSON.stringify({
    url: 'YOUR_SUPABASE_URL',
    key: 'YOUR_SUPABASE_ANON_KEY'
}));
```

## Функционал

- 📋 Просмотр списка чатов
- ➕ Создание нового чата
- ✏️ Переименование чата
- 🗑️ Удаление чата (с каскадным удалением сообщений)
- 📱 Интеграция с Telegram WebApp

## Структура файлов

- `index.html` - Основная HTML структура
- `style.css` - Стили приложения
- `app.js` - JavaScript логика
- `server.py` - Локальный HTTP сервер
- `netlify.toml` - Конфигурация для деплоя на Netlify

