# 🚀 Деплой на Render

Пошаговая инструкция по деплою Telegram бота на Render.

## 📋 Подготовка

### 1. Создайте репозиторий на GitHub (если еще нет)

```bash
git remote add origin https://github.com/ваш-username/TG-AI.git
git push -u origin main
```

## 🔧 Настройка на Render

### Шаг 1: Создайте новый Web Service

1. Зайдите на [Render Dashboard](https://dashboard.render.com)
2. Нажмите **New** → **Web Service**
3. Подключите ваш GitHub репозиторий

### Шаг 2: Настройте параметры деплоя

- **Name**: `tg-ai-bot` (или любое имя)
- **Environment**: `Python 3`
- **Region**: `Frankfurt` (близко к Германии для Gemini API)
- **Branch**: `main`
- **Root Directory**: `.` (корень проекта)
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python bot.py`

### Шаг 3: Настройте Environment Variables

Добавьте следующие переменные окружения в Render Dashboard:

```
TELEGRAM_BOT_TOKEN=ваш_telegram_bot_token
SUPABASE_URL=https://ваш-проект.supabase.co
SUPABASE_KEY=ваш_anon_public_ключ
GEMINI_API_KEYS=ключ1,ключ2,ключ3,ключ4,ключ5
MINI_APP_URL=https://yourai-bottelegram.netlify.app
MAX_USERS_PER_KEY=5
CONTEXT_WINDOW_SIZE=20
```

**Важно:**
- Не добавляйте пробелы вокруг `=`
- Для нескольких Gemini API ключей разделяйте запятыми
- Используйте `anon public` ключ для SUPABASE_KEY (не `service_role`)

### Шаг 4: Деплой

1. Нажмите **Create Web Service**
2. Render автоматически начнет деплой
3. Дождитесь завершения (обычно 2-3 минуты)
4. Проверьте логи на вкладке **Logs**

## 🔍 Проверка работы

### 1. Проверьте логи

В Render Dashboard → ваша служба → **Logs**:

- Должно быть: `Application startup complete`
- Не должно быть ошибок подключения к Supabase
- Не должно быть ошибок Telegram Bot API

### 2. Протестируйте бота

1. Найдите вашего бота в Telegram
2. Отправьте `/start`
3. Бот должен ответить приветствием
4. Проверьте создание чатов

### 3. Обновите Mini App URL в боте

Если Mini App еще не развернут, можете временно оставить:
```
MINI_APP_URL=https://your-app.netlify.app
```

После деплоя Mini App на Netlify обновите эту переменную.

## 📝 Важные моменты

### Health Checks

Render автоматически проверяет здоровье службы. Если бот не отвечает на HTTP-запросы, добавьте простой health endpoint:

```python
# Добавьте в bot.py перед запуском приложения:
from flask import Flask
app = Flask(__name__)

@app.route('/health')
def health():
    return 'OK', 200

# Запустите Flask в отдельном потоке:
import threading
threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
```

Но для Telegram бота это не обязательно - бот работает через webhooks или polling.

### Автоматические деплои

Render автоматически деплоит при каждом push в main ветку GitHub.

### Обновление переменных окружения

1. В Render Dashboard → ваша служба → **Environment**
2. Добавьте/измените переменные
3. Нажмите **Save Changes**
4. Render автоматически перезапустит службу

## 🔧 Устранение проблем

### Бот не отвечает

1. Проверьте логи на ошибки
2. Убедитесь, что `TELEGRAM_BOT_TOKEN` правильный
3. Проверьте подключение к Supabase

### Ошибки Supabase

1. Убедитесь, что миграции выполнены
2. Проверьте правильность `SUPABASE_URL` и `SUPABASE_KEY`
3. Выполните SQL миграции в Supabase Dashboard

### Ошибки Gemini API

1. Проверьте правильность API ключей
2. Убедитесь, что ключи не истекли
3. Проверьте лимиты использования

## 💰 Стоимость

- Render предлагает **бесплатный тариф** с ограничениями:
  - Служба "засыпает" после 15 минут неактивности
  - Просыпается при первом запросе (несколько секунд задержки)
  - Подходит для тестирования и небольших проектов

- Для production рекомендуется **Starter план** ($7/месяц):
  - Служба всегда активна
  - Более быстрый отклик

## 📚 Дополнительные ресурсы

- [Render Documentation](https://render.com/docs)
- [Python на Render](https://render.com/docs/deploy-python)

