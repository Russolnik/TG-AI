"""
Конфигурация приложения
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Gemini API Keys
GEMINI_API_KEYS_STR = os.getenv("GEMINI_API_KEYS", "")
GEMINI_API_KEYS = [key.strip() for key in GEMINI_API_KEYS_STR.split(",") if key.strip()]

# Application Settings
MAX_USERS_PER_KEY = int(os.getenv("MAX_USERS_PER_KEY", "5"))
CONTEXT_WINDOW_SIZE = int(os.getenv("CONTEXT_WINDOW_SIZE", "20"))

# Mini App URL (замените на ваш URL после деплоя на Netlify)
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://your-app.netlify.app")

# Gemini Models Configuration
# Доступные модели Gemini
GEMINI_MODELS = {
    'flash': {
        'name': 'gemini-2.5-flash',
        'vision_name': 'gemini-2.5-flash',
        'display_name': 'Gemini 2.5 Flash (Бесплатно)',
        'available': True,
        'is_free': True
    },
    'pro': {
        'name': 'gemini-2.5-pro',
        'vision_name': 'gemini-2.5-pro',
        'display_name': 'Gemini 2.5 Pro (Требуется подписка)',
        'available': False,  # Пока заблокировано
        'is_free': False
    },
    'imagen': {
        'name': 'gemini-2.5-flash-image',  # Imagen nanoBanana для генерации изображений
        'vision_name': 'gemini-2.5-flash',
        'display_name': 'Imagen (Генерация изображений)',
        'available': True,
        'is_free': True,
        'is_image_generation': True
    }
}

# Модель по умолчанию
DEFAULT_MODEL = 'flash'

# Максимальный размер файла: 200 МБ
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 МБ в байтах

# Проверка обязательных переменных
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен в .env")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase credentials не установлены в .env")
if not GEMINI_API_KEYS:
    raise ValueError("GEMINI_API_KEYS не установлены в .env")

