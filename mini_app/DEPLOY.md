# Инструкция по деплою Mini App

## Проблема с 404 на Netlify

Если вы видите ошибку "Page not found" на Netlify, выполните следующие шаги:

### 1. Проверьте файл `_redirects`

Убедитесь, что файл `_redirects` существует в папке `mini_app`:
```
/*    /index.html   200
```

### 2. Настройка Netlify

#### Вариант A: Через веб-интерфейс Netlify

1. Зайдите на [netlify.com](https://netlify.com)
2. Откройте ваш сайт
3. Перейдите в **Site configuration** → **Build & deploy** → **Deploy settings**
4. Убедитесь, что:
   - **Build command**: пусто
   - **Publish directory**: `mini_app` (или `.` если деплоите всю папку)
5. Сохраните изменения

#### Вариант B: Обновите `netlify.toml`

Убедитесь, что `netlify.toml` содержит правильные настройки редиректов.

### 3. Проверьте файлы

Убедитесь, что все файлы присутствуют:
- ✅ `index.html`
- ✅ `app.js`
- ✅ `style.css`
- ✅ `_redirects`
- ✅ `netlify.toml`

### 4. Локальное тестирование

Перед деплоем протестируйте локально:

```bash
cd mini_app
python server.py
```

Откройте `http://localhost:8000` в браузере и проверьте, что все работает.

### 5. Деплой

#### Через Netlify CLI:
```bash
cd mini_app
netlify deploy --prod
```

#### Через Drag & Drop:
1. Зайдите на [app.netlify.com/drop](https://app.netlify.com/drop)
2. Перетащите всю папку `mini_app`
3. Дождитесь завершения деплоя
4. Скопируйте URL (например: `https://your-app-123.netlify.app`)

### 6. Настройка в боте

Обновите `.env`:
```env
MINI_APP_URL=https://your-app-123.netlify.app
```

Перезапустите бота.

### 7. Настройка Supabase в Mini App

Откройте `mini_app/app.js` и:
1. Замените `YOUR_SUPABASE_URL` на ваш Supabase URL
2. Замените `YOUR_SUPABASE_ANON_KEY` на ваш Supabase Anon Key

Или используйте консоль браузера для настройки:
```javascript
localStorage.setItem('supabase_config', JSON.stringify({
    url: 'YOUR_SUPABASE_URL',
    key: 'YOUR_SUPABASE_ANON_KEY'
}));
```

После этого перезагрузите страницу Mini App.

### 8. Проверка работы

1. Откройте бота в Telegram
2. Нажмите кнопку "📱 Мои Диалоги"
3. Должно открыться окно Mini App
4. Если видите ошибку - откройте консоль браузера (F12) для отладки

## Отладка

### Проверка консоли браузера

В Telegram Desktop можно открыть DevTools:
1. Откройте Mini App
2. Нажмите `Ctrl+Shift+I` (или `Cmd+Option+I` на Mac)
3. Посмотрите вкладку Console на ошибки

### Проверка Network запросов

Во вкладке Network проверьте:
- Запросы к Supabase должны возвращать 200 OK
- Если видите CORS ошибки - проверьте настройки Supabase
- Если видите 404 - проверьте URL в конфиге

## Альтернатива: Локальный сервер с ngrok

Если Netlify не работает, используйте локальный сервер:

```bash
# Терминал 1: Запустите локальный сервер
cd mini_app
python server.py

# Терминал 2: Запустите ngrok
ngrok http 8000

# Обновите .env
MINI_APP_URL=https://your-ngrok-url.ngrok.io
```

