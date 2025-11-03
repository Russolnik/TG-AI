"""
Основной файл Telegram-бота
"""
import logging
import asyncio
import threading
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputFile, LabeledPrice, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, PreCheckoutQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode
import re
import os
import base64
import mimetypes
from io import BytesIO
import config
from database import Database
from api_key_manager import APIKeyManager
from gemini_client import GeminiClient
from handlers import ContentHandlers
from uuid import UUID
from typing import Optional, Dict
from google import genai as new_genai
from google.genai import types
import hmac
import hashlib
from urllib.parse import parse_qsl
import json

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные объекты
db = Database()
key_manager = APIKeyManager(db)
handlers = None  # Инициализируется при первом использовании

# Папка для хранения аватаров
AVATARS_DIR = os.path.join(os.path.dirname(__file__), 'avatars')
os.makedirs(AVATARS_DIR, exist_ok=True)

async def download_and_save_avatar(bot, photo_file, telegram_id: int) -> Optional[str]:
    """
    Скачивает и сохраняет аватар пользователя на сервере
    
    Args:
        bot: Экземпляр Telegram бота
        photo_file: File объект от Telegram
        telegram_id: ID пользователя в Telegram
    
    Returns:
        str: URL для доступа к аватару через сервер или None при ошибке
    """
    try:
        # Определяем расширение файла
        file_extension = 'jpg'  # По умолчанию JPG
        if photo_file.file_path:
            ext = os.path.splitext(photo_file.file_path)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.webp']:
                file_extension = ext.lstrip('.')
        
        # Имя файла: {telegram_id}.{extension}
        filename = f"{telegram_id}.{file_extension}"
        filepath = os.path.join(AVATARS_DIR, filename)
        
        # Скачиваем файл
        photo_bytes = await photo_file.download_as_bytearray()
        
        # Сохраняем на диск (синхронно, т.к. мы уже в async контексте)
        with open(filepath, 'wb') as f:
            f.write(photo_bytes)
        
        logger.info(f"✅ Аватар сохранен для пользователя {telegram_id}: {filename}")
        
        # Возвращаем относительный путь (будет использоваться через endpoint)
        # Формат: /api/avatar/{telegram_id}
        return f"/api/avatar/{telegram_id}"
        
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении аватара для пользователя {telegram_id}: {e}", exc_info=True)
        return None

def validate_telegram_init_data(init_data: str, bot_token: str) -> Optional[Dict]:
    """
    Валидирует initData от Telegram WebApp
    
    Args:
        init_data: Строка initData от Telegram WebApp
        bot_token: Токен бота для валидации
    
    Returns:
        dict: Парсированные данные пользователя или None при ошибке валидации
    """
    try:
        if not init_data or not bot_token:
            logger.warning("[InitData] Отсутствует init_data или bot_token")
            return None
        
        # Парсим query string
        data = dict(parse_qsl(init_data))
        
        # Извлекаем hash
        received_hash = data.pop('hash', '')
        if not received_hash:
            logger.warning("[InitData] Отсутствует hash в initData")
            return None
        
        # Сортируем данные и создаем data_check_string
        data_check_string = '\n'.join(f"{k}={v}" for k, v in sorted(data.items()))
        
        # Создаем секретный ключ из bot_token
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256
        ).digest()
        
        # Вычисляем хеш
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Проверяем hash
        if calculated_hash != received_hash:
            logger.warning("[InitData] ❌ Неверный hash в initData")
            return None
        
        # Парсим user data
        user_data = {}
        if 'user' in data:
            try:
                user_data = json.loads(data['user'])
            except json.JSONDecodeError as e:
                logger.warning(f"[InitData] Ошибка парсинга user data: {e}")
                return None
        
        # Логируем успешную валидацию (без чувствительных данных)
        user_id = user_data.get('id')
        masked_id = f"***{str(user_id)[-4:]}" if user_id else "неизвестен"
        logger.info(f"[InitData] ✅ Валидация успешна для пользователя: {masked_id}")
        
        return user_data
        
    except Exception as e:
        logger.error(f"[InitData] Ошибка валидации initData: {e}", exc_info=True)
        return None

def get_handlers_for_user(telegram_id: int) -> ContentHandlers:
    """Получить обработчики для пользователя с его API-ключом и выбранной моделью"""
    global handlers
    
    api_key = key_manager.get_user_api_key(telegram_id)
    if not api_key:
        raise ValueError(f"Не найден API-ключ для пользователя {telegram_id}")
    
    # Получаем выбранную модель пользователя
    model_name = db.get_user_model(telegram_id)
    
    gemini = GeminiClient(api_key, model_name)
    return ContentHandlers(db, gemini)

async def generate_voice_response(api_key: str, text: str, model_name: str) -> Optional[bytes]:
    """
    Генерация голосового ответа через голосовую модель Gemini
    
    Args:
        api_key: API ключ Gemini
        text: Текст для озвучивания
        model_name: Имя голосовой модели
    
    Returns:
        Байты аудио файла или None при ошибке
    """
    try:
        from google import genai as new_genai
        from google.genai import types
        import asyncio
        
        client = new_genai.Client(api_key=api_key)
        
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=text)],
            ),
        ]
        
        # Конфигурация для генерации аудио
        generate_content_config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
        )
        
        def _generate_audio():
            """Синхронная функция для генерации аудио"""
            chunks = []
            for chunk in client.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=generate_content_config,
            ):
                chunks.append(chunk)
            return chunks
        
        # Запускаем в executor
        chunks = await asyncio.to_thread(_generate_audio)
        
        # Обрабатываем chunks для извлечения аудио
        audio_data = None
        for chunk in chunks:
            if (
                chunk.candidates is None
                or chunk.candidates[0].content is None
                or chunk.candidates[0].content.parts is None
            ):
                continue
            
            part = chunk.candidates[0].content.parts[0]
            
            # Проверяем аудио данные
            if part.inline_data and part.inline_data.data:
                data_buffer = part.inline_data.data
                if isinstance(data_buffer, str):
                    audio_data = base64.b64decode(data_buffer)
                else:
                    audio_data = data_buffer
                logger.info(f"[Генерация голоса] Аудио получено, размер: {len(audio_data) if audio_data else 0}")
        
        return audio_data
        
    except Exception as e:
        logger.error(f"[Генерация голоса] Ошибка: {e}", exc_info=True)
        return None

async def generate_content_direct(api_key: str, prompt: str, reference_image: Optional[bytes] = None, user_model_key: Optional[str] = None) -> tuple[Optional[str], Optional[bytes]]:
    """
    Прямая генерация контента через модель для генерации изображений (без посредничества)
    Может генерировать и текст, и изображение одновременно
    
    Args:
        api_key: API ключ Gemini
        prompt: Текстовый запрос пользователя
        reference_image: Опциональное референсное изображение (байты)
        user_model_key: Ключ модели пользователя из config.GEMINI_MODELS (опционально)
    
    Returns:
        tuple: (текстовый ответ или None, изображение или None)
    """
    try:
        # Создаем клиент с новой библиотекой
        client = new_genai.Client(api_key=api_key)
        
        # Определяем модель для генерации изображений
        # Если у пользователя выбрана модель с поддержкой генерации изображений, используем её
        # Иначе используем специальную модель для генерации изображений
        model = None
        if user_model_key and user_model_key in config.GEMINI_MODELS:
            model_config = config.GEMINI_MODELS[user_model_key]
            if model_config.get('supports_image_generation'):
                model = model_config['name']
        
        # Если не нашли модель с поддержкой генерации изображений, используем специальную модель
        if not model:
            if 'image-generation' in config.GEMINI_MODELS:
                model = config.GEMINI_MODELS['image-generation']['name']
            else:
                # Fallback на хардкод, если модель не найдена в конфиге
                model = "gemini-2.0-flash-image-generation"
        
        logger.info(f"[Прямая генерация] Используется модель: {model}")
        
        # Формируем содержимое запроса
        parts_list = [types.Part.from_text(text=prompt)]
        
        # Если есть референсное изображение, добавляем его
        if reference_image:
            # Определяем MIME тип изображения
            image_mime = "image/png"
            if reference_image.startswith(b'\xff\xd8'):
                image_mime = "image/jpeg"
            elif reference_image.startswith(b'\x89PNG'):
                image_mime = "image/png"
            
            # Пробуем использовать from_bytes, если доступен
            try:
                image_part = types.Part.from_bytes(data=reference_image, mime_type=image_mime)
                parts_list.append(image_part)
            except (AttributeError, TypeError):
                # Если from_bytes не доступен, используем inline_data
                image_base64 = base64.b64encode(reference_image).decode('utf-8')
                try:
                    inline_data_part = types.Part(
                        inline_data=types.Blob(data=image_base64, mime_type=image_mime)
                    )
                    parts_list.append(inline_data_part)
                except:
                    # Альтернативный способ через URI или другой формат
                    logger.warning("Не удалось добавить референсное изображение")
        
        contents = [
            types.Content(
                role="user",
                parts=parts_list,
            ),
        ]
        
        # Конфигурация для генерации изображения и текста одновременно
        generate_content_config = types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        )
        
        # Синхронная функция для streaming
        def _generate_stream():
            chunks = []
            for chunk in client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=generate_content_config,
            ):
                chunks.append(chunk)
            return chunks
        
        # Запускаем в executor, чтобы не блокировать event loop
        chunks = await asyncio.to_thread(_generate_stream)
        
        text_parts = []
        image_data = None
        
        # Обрабатываем chunks
        for chunk in chunks:
            if (
                chunk.candidates is None
                or chunk.candidates[0].content is None
                or chunk.candidates[0].content.parts is None
            ):
                continue
            
            part = chunk.candidates[0].content.parts[0]
            
            # Проверяем изображение
            if part.inline_data and part.inline_data.data:
                data_buffer = part.inline_data.data
                if isinstance(data_buffer, str):
                    image_data = base64.b64decode(data_buffer)
                else:
                    image_data = data_buffer
                logger.info(f"[Прямая генерация] Изображение получено, размер: {len(image_data) if image_data else 0}")
            
            # Проверяем текст
            if hasattr(part, 'text') and part.text:
                text_parts.append(part.text)
        
        # Объединяем текстовые части
        text_response = '\n'.join(text_parts) if text_parts else None
        
        # Логируем результат
        logger.info(f"[Прямая генерация] Результат - текст: {bool(text_response)}, изображение: {bool(image_data)}")
        
        # Если не было получено ни изображения, ни текста, это ошибка
        if not image_data and not text_response:
            logger.warning("[Прямая генерация] Не получен ни текст, ни изображение")
            raise Exception("Не удалось получить ответ от модели - отсутствуют и текст, и изображение")
        
        return (text_response, image_data)
        
    except Exception as e:
        error_msg = str(e)
        error_lower = error_msg.lower()
        
        # Если это ошибка квоты, передаем её дальше с дополнительной информацией
        if any(keyword in error_lower for keyword in ["quota", "429", "resource_exhausted", "limit"]):
            logger.error(f"[Прямая генерация] Ошибка квоты: {e}")
            raise Exception(f"RESOURCE_EXHAUSTED: {error_msg}")
        
        # Для других ошибок также передаем с контекстом
        logger.error(f"[Прямая генерация] Ошибка: {e}", exc_info=True)
        raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    telegram_id = update.effective_user.id
    user = update.effective_user
    
    # Проверяем referral код из параметров команды /start <referral_code>
    referral_code = None
    if context.args and len(context.args) > 0:
        referral_code = context.args[0]
        logger.info(f"[Referral] Обнаружен referral код: {referral_code[:10]}... от пользователя {telegram_id}")
    
    # Получаем данные пользователя из Telegram
    username = user.username if hasattr(user, 'username') and user.username else None
    first_name = user.first_name if hasattr(user, 'first_name') and user.first_name else None
    # Получаем и сохраняем фото профиля (если доступно)
    photo_url = None
    try:
        # Получаем фото профиля пользователя через get_user_profile_photos
        profile_photos = await context.bot.get_user_profile_photos(telegram_id, limit=1)
        if profile_photos and profile_photos.photos:
            # Берем самое большое фото
            photo = profile_photos.photos[0][-1]  # Последний элемент - самое большое фото
            photo_file = await context.bot.get_file(photo.file_id)
            
            # Скачиваем и сохраняем аватар на сервере
            photo_url = await download_and_save_avatar(context.bot, photo_file, telegram_id)
            
    except Exception as e:
        logger.warning(f"Не удалось получить фото пользователя {telegram_id}: {e}")
    
    try:
        # Обрабатываем referral код ДО создания пользователя
        referrer_id = None
        if referral_code:
            # Парсим referral код (формат: ref_<telegram_id> или просто telegram_id)
            try:
                if referral_code.startswith('ref_'):
                    referrer_id = int(referral_code.replace('ref_', '').split('_')[0])  # Берем только ID после ref_
                else:
                    referrer_id = int(referral_code)
                
                # Проверяем что это не сам пользователь
                if referrer_id == telegram_id:
                    logger.warning(f"[Referral] Пользователь пытается использовать свой собственный referral код")
                    referrer_id = None
                else:
                    # Проверяем что пользователь с таким ID существует
                    referrer_user = db.get_user(referrer_id)
                    if not referrer_user:
                        logger.warning(f"[Referral] Пользователь-реферер {referrer_id} не найден")
                        referrer_id = None
                    else:
                        logger.info(f"[Referral] ✅ Найден реферер: {referrer_id}")
            except (ValueError, TypeError):
                logger.warning(f"[Referral] Неверный формат referral кода: {referral_code}")
                referrer_id = None
        
        # Получаем или назначаем ключ пользователю (с данными профиля)
        key_id, api_key, status = key_manager.assign_key_to_user(telegram_id, 
                                                                 username=username, 
                                                                 first_name=first_name, 
                                                                 photo_url=photo_url,
                                                                 referrer_id=referrer_id)
        
        if status == "limit_exceeded":
            await update.message.reply_text(
                "⚠️ Извините, лимит пользователей временно исчерпан. "
                "Пожалуйста, попробуйте позже."
            )
            return
        elif status == "existing_user":
            # Обновляем данные профиля если они изменились (например, обновилось имя или username)
            existing_user = db.get_user(telegram_id)
            if existing_user:
                needs_update = False
                if username and existing_user.get('username') != username:
                    needs_update = True
                if first_name and existing_user.get('first_name') != first_name:
                    needs_update = True
                if photo_url and existing_user.get('photo_url') != photo_url:
                    needs_update = True
                
                if needs_update:
                    db.update_user_profile(telegram_id, username=username, first_name=first_name, photo_url=photo_url)
                    logger.info(f"[Start] ✅ Профиль существующего пользователя обновлен: {telegram_id}")
            
            welcome_msg = (
                "👋 Добро пожаловать обратно!\n\n"
                "Я твой помощник на основе Gemini.\n\n"
                "Что я умею:\n"
                "• 💬 Текстовый чат\n"
                "• 🎙️ Обработка голосовых сообщений\n"
                "• 🎨 Генерация изображений\n"
                "• 🗣️ Live общение с AI\n"
                "• 📷 Анализ фотографий\n"
                "• 📄 Обработка файлов (PDF, TXT, аудио) до 200 МБ\n\n"
                "💡 **Не забудьте обновить параметры о себе!**\n"
                "Используйте кнопку ⚙️ Параметры, чтобы рассказать о себе, своих интересах "
                "или желаемом стиле общения.\n\n"
                "Отправьте мне сообщение или используйте меню для начала!"
            )
        else:
            # Проверяем есть ли активная подписка от referral reward
            has_referral_sub = False
            subscription = db.get_active_subscription(telegram_id)
            if subscription and subscription.get('subscription_type') == 'referral_reward':
                has_referral_sub = True
            
            welcome_msg = (
                "👋 Добро пожаловать!\n\n"
                "Я твой помощник на основе Gemini.\n\n"
            )
            
            if has_referral_sub:
                welcome_msg += "🎁 **Вы получили 3 дня подписки за регистрацию по приглашению!**\n\n"
            
            welcome_msg += (
                "Что я умею:\n"
                "• 💬 Текстовый чат\n"
                "• 🎙️ Обработка голосовых сообщений\n"
                "• 🎨 Генерация изображений\n"
                "• 🗣️ Live общение с AI\n"
                "• 📷 Анализ фотографий\n"
                "• 📄 Обработка файлов (PDF, TXT, аудио) до 200 МБ\n\n"
                "💡 **Не забудьте указать параметры о себе!**\n"
                "Используйте кнопку ⚙️ Параметры, чтобы рассказать о себе, своих интересах, "
                "предпочтениях или желаемом стиле общения. Это поможет мне лучше понимать вас "
                "и давать более персонализированные ответы.\n\n"
                "Отправьте мне сообщение или используйте меню для начала!"
            )
        
        await update.message.reply_text(welcome_msg)
        
        # Устанавливаем постоянное меню с кнопками
        await setup_main_menu(update.message)
        
    except Exception as e:
        masked_id = f"***{str(telegram_id)[-4:]}" if telegram_id else "неизвестен"
        logger.error(f"Ошибка в команде /start для пользователя {masked_id}: {str(e)}")
        await update.message.reply_text(
            "❌ Произошла ошибка при регистрации.\n\n"
            "Пожалуйста, попробуйте позже или обратитесь к администратору."
        )

async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /model - выбор модели AI"""
    telegram_id = update.effective_user.id
    
    try:
        # Получаем текущую модель пользователя
        current_model = db.get_user_model(telegram_id)
        
        # Проверяем подписку
        username = update.effective_user.username
        has_subscription = db.has_active_subscription(telegram_id, username)
        
        # Создаем клавиатуру для выбора модели
        keyboard = []
        for model_key, model_info in config.GEMINI_MODELS.items():
            if model_info['available']:
                # Проверяем, требуется ли подписка для модели
                is_premium = not model_info.get('is_free', True)
                requires_subscription = is_premium and not has_subscription
                
                # Добавляем отметку о текущей выбранной модели
                prefix = "✅ " if model_key == current_model else ""
                
                # Если модель платная и нет подписки - показываем замок
                if requires_subscription:
                    button_text = f"🔒 {model_info['display_name']}"
                    keyboard.append([InlineKeyboardButton(
                        button_text,
                        callback_data="model_locked"
                    )])
                else:
                    button_text = f"{prefix}{model_info['display_name']}"
                    keyboard.append([InlineKeyboardButton(
                        button_text,
                        callback_data=f"model_{model_key}"
                    )])
            else:
                # Заблокированные модели
                button_text = f"🔒 {model_info['display_name']}"
                keyboard.append([InlineKeyboardButton(
                    button_text,
                    callback_data="model_locked"
                )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        current_model_info = config.GEMINI_MODELS.get(
            current_model,
            config.GEMINI_MODELS[config.DEFAULT_MODEL]
        )
        
        # Формируем сообщение с предупреждением о платных моделях
        premium_warning = ""
        if not has_subscription:
            premium_models = [m for m in config.GEMINI_MODELS.values() if not m.get('is_free', True) and m['available']]
            if premium_models:
                premium_warning = "\n\n⚠️ Некоторые модели требуют активной подписки.\nИспользуйте команду /subscription для оформления."
        
        # Формируем описание моделей
        model_descriptions = []
        for model_key, model_info in config.GEMINI_MODELS.items():
            if model_info['available']:
                desc = ""
                if model_info.get('opens_mini_app'):
                    desc = " (Работает через Mini App)"
                elif model_info.get('supports_voice'):
                    desc = " (Поддерживает голосовые ответы)"
                elif model_info.get('supports_image_generation'):
                    desc = " (Поддерживает генерацию изображений)"
                model_descriptions.append(f"• {model_info['display_name']}{desc}")
        
        description_text = "\n".join(model_descriptions) if model_descriptions else "Нет доступных моделей"
        
        message_text = (
            f"🤖 **Выбор модели AI**\n\n"
            f"Текущая модель: **{current_model_info['display_name']}**\n\n"
            f"**Доступные модели:**\n{description_text}\n\n"
            f"Выберите модель из списка ниже:{premium_warning}"
        )
        
        await update.message.reply_text(
            message_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Ошибка в команде /model: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при получении списка моделей."
        )

async def model_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback для выбора модели"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    
    try:
        callback_data = query.data
        
        if callback_data == "model_locked":
            username = query.from_user.username
            has_subscription = db.has_active_subscription(telegram_id, username)
            
            if not has_subscription:
                await query.edit_message_text(
                    "🔒 **Модель недоступна**\n\n"
                    "Для использования этой модели требуется активная подписка.\n\n"
                    "💎 Используйте команду /subscription для оформления подписки.\n\n"
                    "🎁 Или активируйте пробный период командой /trial"
                )
            else:
                await query.edit_message_text(
                    "🔒 Эта модель временно недоступна.\n\n"
                    "Попробуйте выбрать другую модель."
                )
            return
        
        # Извлекаем ключ модели из callback_data
        if callback_data.startswith("model_"):
            model_key = callback_data.replace("model_", "")
            
            if model_key not in config.GEMINI_MODELS:
                await query.edit_message_text("❌ Неизвестная модель.")
                return
            
            model_info = config.GEMINI_MODELS[model_key]
            
            if not model_info['available']:
                await query.edit_message_text(
                    "🔒 Эта модель недоступна. Требуется подписка."
                )
                return
            
            # Проверяем, требуется ли подписка для выбранной модели
            username = query.from_user.username
            is_premium = not model_info.get('is_free', True)
            has_subscription = db.has_active_subscription(telegram_id, username)
            
            if is_premium and not has_subscription:
                await query.edit_message_text(
                    "🔒 **Модель недоступна**\n\n"
                    "Для использования этой модели требуется активная подписка.\n\n"
                    "💎 Используйте команду /subscription для оформления подписки.\n\n"
                    "🎁 Или активируйте пробный период командой /trial",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # Если модель открывает mini app, открываем его вместо смены модели
            if model_info.get('opens_mini_app', False):
                mini_app_mode = model_info.get('mini_app_mode', 'generation')
                mini_app_url = config.MINI_APP_URL
                telegram_id = query.from_user.id
                
                # Убираем завершающий слэш если есть
                mini_app_url = mini_app_url.rstrip('/')
                
                # Добавляем параметры: режим и telegram_id
                mini_app_url_with_mode = f"{mini_app_url}?mode={mini_app_mode}&tg_id={telegram_id}"
                
                # Создаем кнопку с Mini App
                keyboard = [
                    [InlineKeyboardButton(
                        f"📱 Открыть {model_info['display_name']}", 
                        web_app={"url": mini_app_url_with_mode}
                    )]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"📱 **{model_info['display_name']}**\n\n"
                    f"Эта модель работает через Mini App.\n"
                    f"Нажмите кнопку ниже, чтобы открыть.",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # Для бесплатной модели просто обновляем выбор
            # Обновляем модель пользователя
            db.update_user_model(telegram_id, model_key)
            
            await query.edit_message_text(
                f"✅ Модель изменена на **{model_info['display_name']}**\n\n"
                f"Новая модель будет использоваться для всех последующих запросов.",
                parse_mode=ParseMode.MARKDOWN
            )
            
    except Exception as e:
        logger.error(f"Ошибка в callback модели: {e}")
        await query.edit_message_text(
            "❌ Произошла ошибка при смене модели."
        )

async def params_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /params - управление параметрами пользователя"""
    telegram_id = update.effective_user.id
    
    try:
        # Получаем текущие параметры
        parameters = db.get_user_parameters(telegram_id)
        
        # Формируем текст параметров (показываем только profile)
        if parameters:
            # Показываем только profile параметр (основной текст)
            params_text = parameters.get('profile', '')
            if not params_text:
                # Если profile нет, показываем все параметры
                params_text = " ".join([f"{key}: {value}" for key, value in parameters.items()])
            
            # Ограничение до 40 слов для отображения
            words = params_text.split()
            if len(words) > 40:
                params_text = " ".join(words[:40]) + "..."
            message_text = f"Ваши параметры: {params_text}"
        else:
            message_text = "Ваши параметры: не указаны"
        
        # Только 2 кнопки
        keyboard = [
            [InlineKeyboardButton("➕ Добавить/Изменить", callback_data="param_edit")],
        ]
        
        if parameters:
            keyboard.append([InlineKeyboardButton("🗑️ Очистить все", callback_data="param_clear_all")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message_text,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Ошибка в команде /params: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при получении параметров."
        )

async def params_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback для параметров"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    
    try:
        callback_data = query.data
        
        if callback_data == "param_edit":
            parameters = db.get_user_parameters(telegram_id)
            current_text = ""
            if parameters:
                # Показываем только profile
                params_text = parameters.get('profile', '')
                if not params_text:
                    params_text = " ".join([f"{key}: {value}" for key, value in parameters.items()])
                
                words = params_text.split()
                if len(words) > 40:
                    params_text = " ".join(words[:40]) + "..."
                current_text = f"\n\nТекущие параметры: {params_text}"
            
            keyboard = [
                [InlineKeyboardButton("💾 Сохранить", callback_data="param_save")],
                [InlineKeyboardButton("❌ Отменить", callback_data="param_cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"✏️ Введите ваши параметры одним текстом (до 40 слов).{current_text}\n\n"
                "Например: верующий, 25 лет, интересы: программирование музыка спорт",
                reply_markup=reply_markup
            )
            context.user_data['waiting_for_param'] = True
            return
        
        elif callback_data == "param_save":
            # Сохраняем параметры из контекста
            param_text = context.user_data.get('param_text', '')
            if param_text:
                # Получаем существующие параметры и добавляем к ним новый текст
                existing_params = db.get_user_parameters(telegram_id)
                existing_text = existing_params.get('profile', '')
                
                # Объединяем старый и новый текст
                if existing_text:
                    combined_text = f"{existing_text} {param_text}"
                else:
                    combined_text = param_text
                
                # Проверяем количество слов
                words = combined_text.split()
                word_count = len(words)
                
                # Если больше 40 слов, показываем предупреждение, но сохраняем
                if word_count > 40:
                    warning_msg = f"⚠️ Внимание: Ваши параметры содержат {word_count} слов (рекомендуется до 40). Последние {word_count - 40} слов могут быть обрезаны при использовании.\n\n"
                else:
                    warning_msg = ""
                
                # Обрезаем до 40 слов если превышает
                if word_count > 40:
                    combined_text = " ".join(words[:40])
                
                # Сохраняем объединенные параметры
                db.set_user_parameter(telegram_id, "profile", combined_text)
                context.user_data['waiting_for_param'] = None
                context.user_data['param_text'] = None
                
                # Фоновый запрос для инициализации с новыми параметрами
                asyncio.create_task(warmup_gemini_with_params(telegram_id, combined_text))
                
                # Возвращаемся к списку параметров с предупреждением если нужно
                await params_command_callback(query, telegram_id)
                
                if warning_msg:
                    await query.answer(warning_msg, show_alert=True)
            else:
                await query.edit_message_text("❌ Нечего сохранять. Введите параметры сначала.")
            return
        
        elif callback_data == "param_cancel":
            context.user_data['waiting_for_param'] = None
            context.user_data['param_text'] = None
            await params_command_callback(query, telegram_id)
            return
        
        elif callback_data == "param_clear_all":
            keyboard = [
                [InlineKeyboardButton("✅ Да", callback_data="param_confirm_clear")],
                [InlineKeyboardButton("❌ Нет", callback_data="param_cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "Вы уверены?",
                reply_markup=reply_markup
            )
            return
        
        elif callback_data == "param_confirm_clear":
            db.clear_user_parameters(telegram_id)
            await query.edit_message_text("✅ Все параметры удалены.")
            return
        
    except Exception as e:
        logger.error(f"Ошибка в callback параметров: {e}")
        await query.edit_message_text("❌ Произошла ошибка.")

async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /invite или кнопки 'Пригласить друга' - генерация referral ссылки"""
    telegram_id = update.effective_user.id
    
    try:
        # Получаем referral код пользователя
        referral_code = db.get_referral_code(telegram_id)
        
        # Получаем username бота
        bot_username = context.bot.username if context.bot.username else None
        if not bot_username:
            try:
                bot_info = await context.bot.get_me()
                bot_username = bot_info.username
            except Exception as e:
                logger.warning(f"Не удалось получить username бота: {e}")
                bot_username = "YOUR_BOT_USERNAME"
        
        # Формируем referral ссылку
        invite_url = f"https://t.me/{bot_username}?start={referral_code}"
        
        # Формируем сообщение
        message_text = (
            "🎁 **Пригласи друга и получи 3 дня подписки!**\n\n"
            "Поделись этой ссылкой с другом. Когда он зарегистрируется по твоей ссылке, "
            "он получит **3 дня подписки** автоматически!\n\n"
            f"**Твоя referral ссылка:**\n"
            f"`{invite_url}`\n\n"
            "💡 Нажми на ссылку, чтобы скопировать её, или отправь другу напрямую."
        )
        
        # Создаем кнопку для копирования
        keyboard = [
            [InlineKeyboardButton("📋 Скопировать ссылку", callback_data=f"copy_ref_{referral_code}")],
            [InlineKeyboardButton("📤 Поделиться ссылкой", url=f"https://t.me/share/url?url={invite_url}&text=Присоединяйся%20к%20AI%20ассистенту!")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        
        logger.info(f"[Referral] Пользователь {telegram_id} запросил referral ссылку")
        
    except Exception as e:
        logger.error(f"Ошибка в команде /invite для пользователя {telegram_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при генерации referral ссылки.\n\n"
            "Пожалуйста, попробуйте позже."
        )

async def copy_referral_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback для копирования referral ссылки"""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем referral код из callback_data
    referral_code = query.data.replace("copy_ref_", "")
    telegram_id = update.effective_user.id
    
    try:
        # Получаем username бота
        bot_username = context.bot.username if context.bot.username else None
        if not bot_username:
            try:
                bot_info = await context.bot.get_me()
                bot_username = bot_info.username
            except:
                bot_username = "YOUR_BOT_USERNAME"
        
        invite_url = f"https://t.me/{bot_username}?start={referral_code}"
        
        # Отправляем ссылку в новом сообщении (Telegram автоматически делает её кликабельной)
        await query.edit_message_text(
            f"✅ **Ссылка готова!**\n\n"
            f"Твоя referral ссылка:\n"
            f"`{invite_url}`\n\n"
            f"💡 Нажми на ссылку выше, чтобы скопировать её, или отправь другу.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        logger.info(f"[Referral] Пользователь {telegram_id} скопировал referral ссылку")
        
    except Exception as e:
        logger.error(f"Ошибка в copy_referral_callback: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Произошла ошибка. Попробуйте позже."
        )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /menu - обновление меню"""
    await setup_main_menu(update.message)

async def setup_main_menu(message):
    """Настройка постоянного меню с кнопками"""
    mini_app_url = get_mini_app_url()
    # Получаем telegram_id пользователя для передачи в URL
    telegram_id = message.from_user.id if message.from_user else None
    if telegram_id:
        main_url = f"{mini_app_url}/main.html?tg_id={telegram_id}"
    else:
        main_url = f"{mini_app_url}/main.html"
    
    keyboard = [
        [KeyboardButton("📱 Открыть приложение", web_app={"url": main_url})],
        [KeyboardButton("🤖 Модель"), KeyboardButton("⚙️ Параметры")],
        [KeyboardButton("💎 Подписка"), KeyboardButton("🎁 Пробный период")],
        [KeyboardButton("🎁 Пригласить друга"), KeyboardButton("➕ Новый чат")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Отправляем меню - оно автоматически обновится для пользователя
    try:
        await message.reply_text(
            "💡 Меню обновлено! Используйте кнопки ниже для навигации:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.warning(f"Ошибка при установке меню: {e}")
        # Пробуем отправить без текста
        try:
            await message.reply_text("✅", reply_markup=reply_markup)
        except:
            pass

def get_active_chat_for_user(telegram_id: int, context: ContextTypes.DEFAULT_TYPE):
    """
    Получить активный чат пользователя (последний созданный)
    
    Returns:
        tuple: (chat_id: UUID, chat: Dict) или (None, None) если ошибка
    """
    # Используем активный чат по умолчанию
    chat = db.get_user_active_chat(telegram_id)
    if not chat:
        chat = db.create_chat(telegram_id, "Чат 1")
    
    if chat:
        return UUID(chat['chat_id']), chat
    
    return None, None

async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок меню"""
    text = update.message.text
    telegram_id = update.effective_user.id
    
    if text == "🤖 Модель":
        await model_command(update, context)
    elif text == "⚙️ Параметры":
        await params_command(update, context)
    elif text == "💎 Подписка":
        await subscription_command(update, context)
    elif text == "🎁 Пробный период":
        await trial_command(update, context)
    elif text == "➕ Новый чат":
        await new_chat_command(update, context)
    elif text == "📱 Открыть приложение":
        # Кнопка WebApp обрабатывается автоматически Telegram
        # Можно добавить логику здесь если нужно
        pass
    elif text == "🎁 Пригласить друга" or text == "👥 Пригласить друга":
        await invite_command(update, context)

async def new_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание нового чата (старый удаляется)"""
    telegram_id = update.effective_user.id
    
    try:
        # Получаем список всех чатов пользователя
        user_chats = db.get_user_chats(telegram_id)
        
        # Удаляем все старые чаты пользователя
        for chat in user_chats:
            try:
                db.delete_chat(UUID(chat['chat_id']))
            except Exception as e:
                logger.warning(f"Ошибка при удалении чата {chat['chat_id']}: {e}")
        
        # Создаем новый чат
        new_chat = db.create_chat(telegram_id, "Чат 1")
        
        if new_chat:
            await update.message.reply_text(
                f"✅ **Новый чат создан!**\n\n"
                f"Старые чаты удалены. Вы можете начать новый диалог с чистого листа.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("❌ Не удалось создать новый чат.")
    except Exception as e:
        logger.error(f"Ошибка при создании нового чата: {e}")
        await update.message.reply_text("❌ Произошла ошибка при создании чата.")

async def trial_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки '🎁 Пробный период' - активация и информация о пробном периоде"""
    telegram_id = update.effective_user.id
    masked_id = f"***{str(telegram_id)[-4:]}"
    
    try:
        # Получаем статус пробного периода
        trial_status = db.get_trial_status(telegram_id)
        is_active = trial_status.get('is_active', False)
        can_use = trial_status.get('can_use', False)
        trial_used = trial_status.get('trial_used', False)
        hours_remaining = trial_status.get('hours_remaining')
        
        if is_active:
            # Пробный период активен
            message = (
                f"✅ **Пробный период активен!**\n\n"
                f"⏱️ Осталось времени: **{hours_remaining:.1f} часов**\n\n"
                f"🎁 Вы можете использовать все функции бесплатно до окончания пробного периода.\n\n"
                f"💡 После окончания пробного периода потребуется подписка для продолжения использования."
            )
        elif can_use:
            # Можно активировать пробный период
            # Активируем пробный период
            trial_activated = db.activate_trial(telegram_id)
            
            if trial_activated:
                logger.info(f"[Trial] ✅ Пробный период активирован через кнопку для пользователя: {masked_id}")
                message = (
                    f"🎉 **Пробный период активирован!**\n\n"
                    f"⏱️ Срок действия: **24 часа**\n\n"
                    f"🎁 Теперь вы можете использовать все функции бесплатно в течение пробного периода.\n\n"
                    f"💡 После окончания пробного периода потребуется подписка для продолжения использования."
                )
            else:
                message = (
                    f"❌ Не удалось активировать пробный период.\n\n"
                    f"Пожалуйста, попробуйте позже или обратитесь в поддержку."
                )
        else:
            # Пробный период уже использован
            message = (
                f"⏰ **Пробный период уже использован**\n\n"
                f"📅 Ваш пробный период закончился.\n\n"
                f"💎 Для продолжения использования функций требуется подписка.\n\n"
                f"Используйте команду /subscription для оформления подписки."
            )
            
            # Добавляем кнопку оформления подписки
            keyboard = [
                [InlineKeyboardButton("💎 Оформить подписку", callback_data="sub_menu")]
            ]
            
            await update.message.reply_text(
                message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Ошибка в команде пробного периода: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при проверке пробного периода. Пожалуйста, попробуйте позже."
        )

async def subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /subscription - информация о подписке и покупка"""
    telegram_id = update.effective_user.id
    user = update.effective_user
    
    try:
        # Получаем текущую подписку
        subscription = db.get_active_subscription(telegram_id)
        
        # Получаем статус пробного периода
        trial_status = db.get_trial_status(telegram_id)
        is_trial_active = trial_status.get('is_active', False)
        
        # Формируем единое окно со статусом подписки сверху и кнопками покупки снизу
        message_text = ""
        keyboard = []
        
        if subscription or is_trial_active:
            # Статус подписки (сверху)
            if subscription:
                # Если есть обычная подписка
                from datetime import datetime, timezone, timedelta
                end_date = datetime.fromisoformat(subscription['end_date'].replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                days_left = max(0, (end_date - now).days)
                hours_left = max(0, (end_date - now).total_seconds() / 3600)
                
                status_text = ""
                if days_left > 0:
                    status_text = f"{days_left} {days_left == 1 and 'день' or (days_left < 5 and 'дня' or 'дней')}"
                elif hours_left > 0:
                    status_text = f"{int(hours_left)} ч."
                
                # Проверяем, можно ли вернуть подписку (в течение 24 часов после покупки)
                start_date = datetime.fromisoformat(subscription['start_date'].replace('Z', '+00:00'))
                time_since_purchase = now - start_date
                can_refund = time_since_purchase <= timedelta(hours=24)
                payment_charge_id = subscription.get('payment_charge_id')
                is_stars_payment = payment_charge_id is not None
                
                message_text = (
                    f"💎 **Статус подписки**\n\n"
                    f"• Тип: {subscription['subscription_type'].replace('_', ' ').title()}\n"
                    f"• Действует до: {end_date.strftime('%d.%m.%Y %H:%M')}\n"
                    f"• Осталось: {status_text}\n\n"
                    f"✅ У вас есть доступ ко всем платным моделям.\n\n"
                    f"{'=' * 30}\n\n"
                )
                
                # Кнопки управления подпиской (если можно вернуть)
                if can_refund:
                    if is_stars_payment:
                        keyboard.append([InlineKeyboardButton("💸 Отменить покупку (Stars)", callback_data="refund_stars")])
                    else:
                        keyboard.append([InlineKeyboardButton("💸 Запросить возврат", callback_data="refund_manual")])
            elif is_trial_active:
                # Если активен пробный период
                hours_remaining = trial_status.get('hours_remaining', 0)
                days_remaining = max(0, int(hours_remaining / 24))
                hours_remain = max(0, int(hours_remaining % 24))
                
                status_text = ""
                if days_remaining > 0:
                    status_text = f"{days_remaining} {days_remaining == 1 and 'день' or (days_remaining < 5 and 'дня' or 'дней')}"
                    if hours_remain > 0:
                        status_text += f" {hours_remain} ч."
                elif hours_remain > 0:
                    status_text = f"{hours_remain} ч."
                
                message_text = (
                    f"🎁 **Статус пробного периода**\n\n"
                    f"• Осталось: {status_text}\n\n"
                    f"✅ У вас есть доступ ко всем платным моделям.\n\n"
                    f"💡 После окончания пробного периода подписка не будет продлена автоматически.\n\n"
                    f"{'=' * 30}\n\n"
                )
        
        # Добавляем раздел покупки подписки (внизу)
        message_text += (
            "💎 **Оформление подписки**\n\n"
            "Выберите способ оплаты:\n\n"
            "💰 **Оплата через Telegram Stars:**\n"
            "• 1 месяц — 125 ⭐ (~200₽)\n"
            "• 3 месяца — 348 ⭐ (~500₽)\n"
            "• 6 месяцев — 626 ⭐ (~900₽)\n\n"
            "💬 **Оплата через создателя:**\n"
            "• 1 месяц — 200₽\n"
            "• 3 месяца — 500₽\n"
            "• 6 месяцев — 900₽\n\n"
            "Выберите вариант ниже:"
        )
        
        # Кнопки покупки подписки
        keyboard.extend([
            [
                InlineKeyboardButton("💳 1 месяц (125⭐)", callback_data="sub_stars_1"),
                InlineKeyboardButton("💬 Написать (200₽)", callback_data="sub_manual_1")
            ],
            [
                InlineKeyboardButton("💳 3 месяца (348⭐)", callback_data="sub_stars_3"),
                InlineKeyboardButton("💬 Написать (500₽)", callback_data="sub_manual_3")
            ],
            [
                InlineKeyboardButton("💳 6 месяцев (626⭐)", callback_data="sub_stars_6"),
                InlineKeyboardButton("💬 Написать (900₽)", callback_data="sub_manual_6")
            ]
        ])
        
        # Кнопка связи с создателем (отдельно снизу)
        creator_username = config.CREATOR_USERNAME
        if creator_username:
            support_message = f"Здравствуйте! У меня вопрос по подписке.\n\nМой ID: {telegram_id}"
            support_url = f"https://t.me/{creator_username}?text={support_message}"
            keyboard.append([InlineKeyboardButton("💬 Связаться с создателем", url=support_url)])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await update.message.reply_text(
            message_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Ошибка в команде /subscription: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при получении информации о подписке. Попробуйте позже."
        )

async def subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback для управления подпиской"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    telegram_id = query.from_user.id
    user = query.from_user
    
    try:
        # Обработка активации пробного периода через кнопку
        if callback_data == "trial_activate":
            trial_status = db.get_trial_status(telegram_id)
            can_use = trial_status.get('can_use', False)
            is_active = trial_status.get('is_active', False)
            
            if is_active:
                hours_remaining = trial_status.get('hours_remaining', 0)
                await query.edit_message_text(
                    f"✅ **Пробный период уже активен!**\n\n"
                    f"⏱️ Осталось времени: **{hours_remaining:.1f} часов**\n\n"
                    f"🎁 Вы можете использовать все функции бесплатно до окончания пробного периода.",
                    parse_mode=ParseMode.MARKDOWN
                )
            elif can_use:
                trial_activated = db.activate_trial(telegram_id)
                if trial_activated:
                    await query.edit_message_text(
                        f"🎉 **Пробный период активирован!**\n\n"
                        f"⏱️ Срок действия: **24 часа**\n\n"
                        f"🎁 Теперь вы можете использовать все функции бесплатно в течение пробного периода.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await query.edit_message_text(
                        "❌ Не удалось активировать пробный период. Попробуйте позже.",
                        parse_mode=ParseMode.MARKDOWN
                    )
            else:
                await query.edit_message_text(
                    "⏰ Пробный период уже использован.\n\n"
                    "💎 Для продолжения использования функций требуется подписка.",
                    parse_mode=ParseMode.MARKDOWN
                )
            return
        
        # Обработка кнопки "Оформить подписку" из пробного периода
        if callback_data == "sub_menu":
            # Показываем меню покупки подписки
            message_text = (
                "💎 **Оформление подписки**\n\n"
                "Выберите способ оплаты:\n\n"
                "💰 **Оплата через Telegram Stars:**\n"
                "• 1 месяц — 125 ⭐ (~200₽)\n"
                "• 3 месяца — 348 ⭐ (~500₽)\n"
                "• 6 месяцев — 626 ⭐ (~900₽)\n\n"
                "💬 **Оплата через создателя:**\n"
                "• 1 месяц — 200₽\n"
                "• 3 месяца — 500₽\n"
                "• 6 месяцев — 900₽\n\n"
                "Выберите вариант ниже:"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("💳 1 месяц (125⭐)", callback_data="sub_stars_1"),
                    InlineKeyboardButton("💬 Написать (200₽)", callback_data="sub_manual_1")
                ],
                [
                    InlineKeyboardButton("💳 3 месяца (348⭐)", callback_data="sub_stars_3"),
                    InlineKeyboardButton("💬 Написать (500₽)", callback_data="sub_manual_3")
                ],
                [
                    InlineKeyboardButton("💳 6 месяцев (626⭐)", callback_data="sub_stars_6"),
                    InlineKeyboardButton("💬 Написать (900₽)", callback_data="sub_manual_6")
                ]
            ]
            
            await query.edit_message_text(
                message_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # Обработка оплаты через Telegram Stars
        if callback_data.startswith("sub_stars_"):
            months = int(callback_data.split("_")[-1])
            
            # Расчет цены в Stars
            # 125⭐ за 1 месяц (≈200₽)
            # 348⭐ за 3 месяца (≈500₽)
            # 626⭐ за 6 месяцев (≈900₽)
            stars_amounts = {1: 125, 3: 348, 6: 626}
            stars_amount = stars_amounts.get(months, 125 * months)
            
            # Создаем invoice для Telegram Stars
            # Важно: для Stars используется currency="XTR" и amount в минимальных единицах (1 star = 1 unit, НЕ 100!)
            prices = [LabeledPrice(f"Подписка {months} {'месяц' if months == 1 else 'месяца' if months < 5 else 'месяцев'}", stars_amount)]
            
            try:
                await context.bot.send_invoice(
                    chat_id=telegram_id,
                    title=f"Подписка на {months} {'месяц' if months == 1 else 'месяца' if months < 5 else 'месяцев'}",
                    description=f"Доступ ко всем платным моделям (Live и Generation) на {months} {'месяц' if months == 1 else 'месяца' if months < 5 else 'месяцев'}",
                    payload=f"subscription_{months}_months_stars_{telegram_id}",
                    provider_token="",  # Для Stars не нужен provider_token
                    currency="XTR",  # Telegram Stars currency code
                    prices=prices,
                    is_flexible=False
                )
                
                await query.edit_message_text(
                    f"💳 **Оплата через Telegram Stars**\n\n"
                    f"Отправлен счет на оплату {stars_amount} ⭐ за {months} {'месяц' if months == 1 else 'месяца' if months < 5 else 'месяцев'} подписки.\n\n"
                    f"После оплаты подписка будет активирована автоматически.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as invoice_error:
                logger.error(f"Ошибка при создании invoice: {invoice_error}", exc_info=True)
                await query.edit_message_text(
                    "❌ Ошибка при создании счета на оплату. Попробуйте позже или выберите оплату через создателя.",
                    parse_mode=ParseMode.MARKDOWN
                )
        
        # Обработка оплаты через создателя
        elif callback_data.startswith("sub_manual_"):
            months = int(callback_data.split("_")[-1])
            prices_rub = {1: 200, 3: 500, 6: 900}
            price = prices_rub.get(months, 200 * months)
            
            # Получаем имя пользователя для сообщения
            user_name = user.first_name or "Пользователь"
            user_username = user.username or ""
            
            # Формируем текст сообщения для создания
            period_text = f"{months} {'месяц' if months == 1 else 'месяца' if months < 5 else 'месяцев'}"
            message_text = (
                f"Здравствуйте! Хочу оформить подписку на {period_text} за {price}₽.\n\n"
                f"Мой ID: {telegram_id}"
            )
            
            # Создаем URL для перехода к создателю с готовым текстом
            creator_username = config.CREATOR_USERNAME
            telegram_url = f"https://t.me/{creator_username}?text={message_text}"
            
            try:
                await query.edit_message_text(
                    f"💬 **Оплата через создателя**\n\n"
                    f"📋 **Детали заказа:**\n"
                    f"• Подписка: {period_text}\n"
                    f"• Сумма: {price}₽\n\n"
                    f"Нажмите на кнопку ниже, чтобы перейти к создателю с готовым сообщением.\n\n"
                    f"После подтверждения оплаты создателем ваша подписка будет активирована.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"💬 Написать @{creator_username}", url=telegram_url)]
                    ])
                )
                
                logger.info(f"[Подписка] Пользователь {telegram_id} выбрал оплату через создателя: {period_text} за {price}₽")
                
            except Exception as send_error:
                logger.error(f"Ошибка при создании кнопки: {send_error}", exc_info=True)
                await query.edit_message_text(
                    f"❌ Ошибка. Пожалуйста, напишите создателю напрямую: @{creator_username}\n\n"
                    f"Текст сообщения:\n{message_text}",
                    parse_mode=ParseMode.MARKDOWN
                )
        
        # Обработка возврата через Stars
        elif callback_data == "refund_stars":
            subscription = db.get_active_subscription(telegram_id)
            if not subscription:
                await query.edit_message_text(
                    "❌ Подписка не найдена.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            payment_charge_id = subscription.get('payment_charge_id')
            if not payment_charge_id:
                await query.edit_message_text(
                    "❌ Информация о платеже не найдена. Возврат недоступен.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # Проверяем, прошло ли 24 часа
            from datetime import datetime, timezone, timedelta
            start_date = datetime.fromisoformat(subscription['start_date'].replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            time_since_purchase = now - start_date
            
            if time_since_purchase > timedelta(hours=24):
                await query.edit_message_text(
                    "❌ Возврат доступен только в течение 24 часов с момента покупки.\n"
                    f"Прошло: {int(time_since_purchase.total_seconds() / 3600)} часов.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            try:
                # Выполняем возврат через Telegram Bot API
                # Метод refundStarPayment (версия API может отличаться)
                try:
                    # Пробуем новый метод (python-telegram-bot >= 21.0)
                    refund_result = await context.bot.refund_star_payment(
                        user_id=telegram_id,
                        telegram_payment_charge_id=payment_charge_id
                    )
                except AttributeError:
                    # Если метода нет, используем прямой вызов API
                    from telegram.request import HTTPXRequest
                    import httpx
                    
                    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/refundStarPayment"
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            url,
                            json={
                                "user_id": telegram_id,
                                "telegram_payment_charge_id": payment_charge_id
                            }
                        )
                        refund_result = response.status_code == 200 and response.json().get("ok", False)
                
                if refund_result:
                    # Деактивируем подписку
                    db.deactivate_subscription(telegram_id)
                    
                    # Уведомляем создателя
                    user_name = user.first_name or "Пользователь"
                    user_username = user.username or f"ID: {telegram_id}"
                    try:
                        await context.bot.send_message(
                            chat_id=config.CREATOR_TELEGRAM_ID,
                            text=(
                                f"💸 **Возврат через Stars**\n\n"
                                f"👤 Пользователь: {user_name}"
                                f"{' (@' + user_username + ')' if user_username else ''}\n"
                                f"📊 ID: {telegram_id}\n"
                                f"🆔 Payment Charge ID: `{payment_charge_id}`\n\n"
                                f"Подписка деактивирована."
                            ),
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except:
                        pass
                    
                    await query.edit_message_text(
                        "✅ **Возврат выполнен**\n\n"
                        "💰 Оплата возвращена на ваш счет Telegram Stars.\n"
                        "Подписка деактивирована.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    logger.info(f"[Refund] ✅ Возврат Stars выполнен для пользователя {telegram_id}")
                else:
                    await query.edit_message_text(
                        "❌ Не удалось выполнить возврат. Обратитесь в поддержку.",
                        parse_mode=ParseMode.MARKDOWN
                    )
            except Exception as refund_error:
                logger.error(f"[Refund] Ошибка возврата Stars: {refund_error}", exc_info=True)
                await query.edit_message_text(
                    f"❌ Ошибка при возврате: {str(refund_error)}\n\n"
                    "Пожалуйста, обратитесь в поддержку.",
                    parse_mode=ParseMode.MARKDOWN
                )
        
        # Обработка возврата через создателя (денежная оплата)
        elif callback_data == "refund_manual":
            subscription = db.get_active_subscription(telegram_id)
            if not subscription:
                await query.edit_message_text(
                    "❌ Подписка не найдена.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # Формируем сообщение для создателя
            user_name = user.first_name or "Пользователь"
            user_username = user.username or ""
            subscription_type = subscription['subscription_type']
            
            from datetime import datetime, timezone
            start_date = datetime.fromisoformat(subscription['start_date'].replace('Z', '+00:00'))
            end_date = datetime.fromisoformat(subscription['end_date'].replace('Z', '+00:00'))
            
            message_to_creator = (
                f"💸 **Запрос на возврат**\n\n"
                f"👤 Пользователь: {user_name}"
                f"{' (@' + user_username + ')' if user_username else ''}\n"
                f"📊 ID: {telegram_id}\n"
                f"💎 Подписка: {subscription_type.replace('_', ' ').title()}\n"
                f"📅 Оформлена: {start_date.strftime('%d.%m.%Y %H:%M')}\n"
                f"📅 Действует до: {end_date.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"Пользователь запросил возврат денежных средств."
            )
            
            # Создаем кнопку для перехода к создателю
            creator_username = config.CREATOR_USERNAME
            telegram_url = f"https://t.me/{creator_username}?text=Хочу сделать возврат. Вот моя подписка и мои данные:\n\nID: {telegram_id}\nПодписка: {subscription_type}"
            
            try:
                # Отправляем уведомление создателю
                await context.bot.send_message(
                    chat_id=config.CREATOR_TELEGRAM_ID,
                    text=message_to_creator,
                    parse_mode=ParseMode.MARKDOWN
                )
                
                await query.edit_message_text(
                    f"💬 **Запрос на возврат отправлен**\n\n"
                    f"📋 **Ваши данные:**\n"
                    f"• ID: {telegram_id}\n"
                    f"• Подписка: {subscription_type.replace('_', ' ').title()}\n\n"
                    f"Нажмите на кнопку ниже, чтобы перейти к создателю с готовым сообщением.\n\n"
                    f"Создатель свяжется с вами для подтверждения возврата.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"💬 Написать @{creator_username}", url=telegram_url)]
                    ])
                )
                logger.info(f"[Refund] Запрос на возврат отправлен создателю от пользователя {telegram_id}")
            except Exception as send_error:
                logger.error(f"[Refund] Ошибка отправки запроса: {send_error}")
                await query.edit_message_text(
                    f"❌ Ошибка. Пожалуйста, напишите создателю напрямую: @{creator_username}\n\n"
                    f"Укажите:\n• Ваш ID: {telegram_id}\n• Тип подписки: {subscription_type}",
                    parse_mode=ParseMode.MARKDOWN
                )
        
    except Exception as e:
        logger.error(f"Ошибка в subscription_callback: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Произошла ошибка. Пожалуйста, попробуйте позже.",
            parse_mode=ParseMode.MARKDOWN
        )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик pre-checkout query для Telegram Stars"""
    query = update.pre_checkout_query
    telegram_id = query.from_user.id
    
    try:
        # Парсим payload для получения информации о подписке
        payload = query.invoice_payload
        if payload.startswith("subscription_") and "_stars_" in payload:
            # Формат: subscription_{months}_months_stars_{telegram_id}
            parts = payload.split("_")
            months = int(parts[1])
            
            masked_id = f"***{str(telegram_id)[-4:]}"
            logger.info(f"[Payment] Pre-checkout запрос для подписки {months} месяцев от пользователя: {masked_id}")
            
            # Одобряем платеж
            await query.answer(ok=True)
        else:
            logger.warning(f"[Payment] Неизвестный payload: {payload}")
            await query.answer(ok=False, error_message="Неизвестный тип подписки")
            
    except Exception as e:
        logger.error(f"[Payment] Ошибка в precheckout: {e}", exc_info=True)
        await query.answer(ok=False, error_message="Ошибка при обработке платежа")

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик успешного платежа через Telegram Stars"""
    payment = update.message.successful_payment
    telegram_id = update.effective_user.id
    user = update.effective_user
    
    try:
        # Парсим payload
        payload = payment.invoice_payload
        if payload.startswith("subscription_") and "_stars_" in payload:
            parts = payload.split("_")
            months = int(parts[1])
            
            subscription_type_map = {1: "1_month", 3: "3_months", 6: "6_months"}
            subscription_type = subscription_type_map.get(months, "1_month")
            
            masked_id = f"***{str(telegram_id)[-4:]}"
            # payment.total_amount уже в минимальных единицах (1 star = 1 unit)
            stars_paid = payment.total_amount
            telegram_payment_charge_id = payment.telegram_payment_charge_id  # Для возврата
            
            logger.info(f"[Payment] ✅ Успешный платеж {stars_paid} ⭐ за {months} месяцев от пользователя: {masked_id}")
            
            # Создаем подписку (с сохранением payment_charge_id для возврата)
            subscription = db.create_subscription(telegram_id, subscription_type, payment_charge_id=telegram_payment_charge_id)
            
            if subscription:
                user_name = user.first_name or "Пользователь"
                user_username = user.username or f"ID: {telegram_id}"
                
                # Отправляем уведомление создателю
                try:
                    creator_message = (
                        f"💰 **Новая оплата через Telegram Stars**\n\n"
                        f"👤 Пользователь: {user_name}"
                        f"{' (@' + user_username + ')' if user_username else ''}\n"
                        f"📊 ID: {telegram_id}\n"
                        f"💎 Подписка: {months} {'месяц' if months == 1 else 'месяца' if months < 5 else 'месяцев'}\n"
                        f"⭐ Сумма: {stars_paid} ⭐\n"
                        f"🆔 Payment Charge ID: `{telegram_payment_charge_id}`\n\n"
                        f"Подписка активирована автоматически."
                    )
                    await context.bot.send_message(
                        chat_id=config.CREATOR_TELEGRAM_ID,
                        text=creator_message,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    logger.info(f"[Payment] ✅ Уведомление отправлено создателю о платеже от {masked_id}")
                except Exception as notify_error:
                    logger.error(f"[Payment] Ошибка отправки уведомления создателю: {notify_error}")
                
                await update.message.reply_text(
                    f"✅ **Подписка активирована!**\n\n"
                    f"💎 Подписка на {months} {'месяц' if months == 1 else 'месяца' if months < 5 else 'месяцев'} успешно активирована.\n\n"
                    f"🎉 Теперь у вас есть доступ ко всем платным моделям:\n"
                    f"• 🗣️ Live общение\n"
                    f"• 🎨 Генерация изображений\n\n"
                    f"💡 **Возврат:** Вы можете вернуть оплату в течение 24 часов, если что-то не устроит.\n"
                    f"Используйте команду /subscription для управления подпиской.\n\n"
                    f"Спасибо за использование нашего сервиса!",
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info(f"[Payment] ✅ Подписка создана для пользователя: {masked_id}")
            else:
                await update.message.reply_text(
                    "❌ Произошла ошибка при активации подписки. Пожалуйста, обратитесь в поддержку.",
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.error(f"[Payment] ❌ Ошибка создания подписки для пользователя: {masked_id}")
        else:
            logger.warning(f"[Payment] Неизвестный payload в successful_payment: {payload}")
            
    except Exception as e:
        logger.error(f"[Payment] Ошибка в successful_payment_handler: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при обработке платежа. Пожалуйста, обратитесь в поддержку.",
            parse_mode=ParseMode.MARKDOWN
        )

async def start_subscription_report(telegram_id: int):
    """Запустить автоматический отчет при активации подписки"""
    try:
        # Здесь можно добавить логику для автоматического отчета
        # Например, отправка статистики, создание уведомления и т.д.
        masked_id = f"***{str(telegram_id)[-4:]}" if telegram_id else "неизвестен"
        logger.info(f"[Подписка] Запуск автоматического отчета для пользователя {masked_id}")
        
        # Пример: можно отправить уведомление пользователю через бота
        # Для этого нужен доступ к боту, но так как функция вызывается из callback,
        # можно использовать context или создать отдельную функцию
        
        # Пока просто логируем
        subscription = db.get_active_subscription(telegram_id)
        if subscription:
            masked_id = f"***{str(telegram_id)[-4:]}" if telegram_id else "неизвестен"
            logger.info(f"[Подписка] Отчет: Пользователь {masked_id} активировал подписку {subscription['subscription_type']}")
        
    except Exception as e:
        logger.error(f"[Подписка] Ошибка при запуске отчета: {e}")

async def about_project_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды "О проекте" - открывает страницу О проекте"""
    try:
        mini_app_url = get_mini_app_url()
        telegram_id = update.effective_user.id
        about_url = f"{mini_app_url}/about.html?tg_id={telegram_id}"
        
        logger.info(f"Открытие страницы 'О проекте' с URL: {about_url}")
        
        # Создаем кнопку с Mini App
        keyboard = [
            [InlineKeyboardButton("ℹ️ О проекте", web_app={"url": about_url})]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "📋 Страница о проекте",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка в команде 'О проекте': {e}", exc_info=True)
        await update.message.reply_text("❌ Произошла ошибка при открытии страницы.")

async def open_app_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды "Открыть приложение" - открывает главную страницу Mini App"""
    try:
        mini_app_url = get_mini_app_url()
        telegram_id = update.effective_user.id
        main_url = f"{mini_app_url}/main.html?tg_id={telegram_id}"
        
        logger.info(f"Открытие главной страницы Mini App: {main_url} (telegram_id: {telegram_id})")
        
        # Создаем кнопку с Mini App
        keyboard = [
            [InlineKeyboardButton("📱 Открыть приложение", web_app={"url": main_url})]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🚀 Добро пожаловать в AI Assistant!\n\n"
            "Выберите режим работы: Live общение или Генерация изображений",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка в команде 'Открыть приложение': {e}", exc_info=True)
        await update.message.reply_text("❌ Произошла ошибка при открытии приложения.")

def get_mini_app_url():
    """Получить URL Mini App с проверкой"""
    mini_app_url = config.MINI_APP_URL
    
    if not mini_app_url or mini_app_url == "https://your-app.netlify.app":
        mini_app_url = "https://yourai-bottelegram.netlify.app"
    
    mini_app_url = mini_app_url.rstrip('/')
    
    if not mini_app_url.startswith("https://"):
        logger.error(f"Неверный формат MINI_APP_URL: {mini_app_url}")
        mini_app_url = "https://yourai-bottelegram.netlify.app"
    
    return mini_app_url

async def delete_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление текущего чата и всех сообщений"""
    telegram_id = update.effective_user.id
    
    try:
        # Получаем активный чат
        chat = db.get_user_active_chat(telegram_id)
        
        if not chat:
            await update.message.reply_text("❌ У вас нет активного чата для удаления.")
            return
        
        chat_id = UUID(chat['chat_id'])
        chat_title = chat.get('title', 'Чат')
        
        # Подтверждение удаления
        keyboard = [
            [
                InlineKeyboardButton("✅ Да", callback_data="chat_delete_confirm"),
                InlineKeyboardButton("❌ Нет", callback_data="chat_delete_cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Вы уверены, что хотите удалить чат **{chat_title}**?",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Сохраняем chat_id в контексте для подтверждения
        context.user_data['pending_delete_chat_id'] = str(chat_id)
        
    except Exception as e:
        logger.error(f"Ошибка при удалении чата: {e}")
        await update.message.reply_text("❌ Произошла ошибка при удалении чата.")

async def chat_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback для удаления чата"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    
    try:
        callback_data = query.data
        
        if callback_data == "chat_delete_confirm":
            chat_id_str = context.user_data.get('pending_delete_chat_id')
            if not chat_id_str:
                await query.edit_message_text("❌ Ошибка: чат не найден.")
                return
            
            chat_id = UUID(chat_id_str)
            
            # Удаляем чат (каскадное удаление всех сообщений)
            if db.delete_chat(chat_id):
                context.user_data['pending_delete_chat_id'] = None
                
                # Проверяем, есть ли еще чаты у пользователя
                user_chats = db.get_user_chats(telegram_id)
                if user_chats:
                    # Делаем первый доступный чат активным (последний созданный)
                    new_active_chat = sorted(user_chats, key=lambda x: x['created_at'], reverse=True)[0]
                    await query.edit_message_text(
                        f"✅ Чат удален!\n\n"
                        f"Активным теперь является чат: **{new_active_chat.get('title', 'Чат')}**",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    # Создаем новый чат если нет других
                    new_chat = db.create_chat(telegram_id, "Чат 1")
                    await query.edit_message_text(
                        f"✅ Чат удален!\n\n"
                        f"Создан новый чат для продолжения работы.",
                        parse_mode=ParseMode.MARKDOWN
                    )
            else:
                await query.edit_message_text("❌ Не удалось удалить чат.")
                
        elif callback_data == "chat_delete_cancel":
            context.user_data['pending_delete_chat_id'] = None
            await query.edit_message_text("Отменено.")
            
    except Exception as e:
        logger.error(f"Ошибка в callback удаления чата: {e}")
        await query.edit_message_text("❌ Произошла ошибка.")

def format_response_for_telegram(text: str) -> str:
    """
    Форматирует ответ для Telegram с точным сохранением форматирования Gemini
    и добавлением монохромных ссылок. Экранирует HTML спецсимволы для безопасности.
    """
    if not text:
        return ""
    
    # Экранируем HTML спецсимволы
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    
    # Заменяем Markdown ссылки на HTML с монохромным стилем
    # Формат: [текст](url) -> <a href="url">текст</a>
    def replace_link(match):
        link_text = match.group(1).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        link_url = match.group(2)
        # Проверяем что URL валидный
        if not link_url.startswith(('http://', 'https://')):
            return match.group(0)  # Возвращаем как было, если не валидный URL
        return f'<a href="{link_url}">{link_text}</a>'
    
    # Обрабатываем Markdown ссылки [текст](url) - более безопасный паттерн
    text = re.sub(r'\[([^\]]*)\]\(([^)]*)\)', replace_link, text)
    
    # Конвертируем Markdown в HTML
    # Жирный текст **текст** -> <b>текст</b> (но только если четное количество **)
    # Обрабатываем попарно
    parts = text.split('**')
    result_parts = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            # Обычный текст - обрабатываем курсив и код
            # Курсив *текст* -> <i>текст</i> (но не если это часть **)
            part = re.sub(r'(?<!\*)\*([^*]+?)\*(?!\*)', r'<i>\1</i>', part)
            # Код `текст` -> <code>текст</code>
            part = re.sub(r'`([^`]+)`', r'<code>\1</code>', part)
            result_parts.append(part)
        else:
            # Жирный текст
            result_parts.append(f'<b>{part}</b>')
    text = ''.join(result_parts)
    
    # Обрабатываем код блоки ```текст``` -> <pre><code>текст</code></pre>
    text = re.sub(r'```([^`]+)```', r'<pre><code>\1</code></pre>', text)
    
    return text

async def safe_send_message(update: Update, text: str, max_length: int = 4096):
    """
    Безопасная отправка сообщения с разбиением на части и обработкой форматирования
    """
    if not text:
        return
    
    # Пробуем отправить с HTML форматированием
    try:
        formatted = format_response_for_telegram(text)
        # Разбиваем на части если слишком длинное
        if len(formatted) > max_length:
            # Разбиваем по предложениям или абзацам
            parts = []
            current_part = ""
            for line in formatted.split('\n'):
                if len(current_part) + len(line) + 1 > max_length and current_part:
                    parts.append(current_part)
                    current_part = line
                else:
                    current_part += ('\n' if current_part else '') + line
            if current_part:
                parts.append(current_part)
            
            for part in parts:
                await update.message.reply_text(part, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(formatted, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"Ошибка HTML форматирования: {e}, пробуем без форматирования")
        try:
            # Пробуем как обычный текст, разбивая если нужно
            if len(text) > max_length:
                parts = []
                current_part = ""
                for line in text.split('\n'):
                    if len(current_part) + len(line) + 1 > max_length and current_part:
                        parts.append(current_part)
                        current_part = line
                    else:
                        current_part += ('\n' if current_part else '') + line
                if current_part:
                    parts.append(current_part)
                
                for part in parts:
                    await update.message.reply_text(part)
            else:
                await update.message.reply_text(text)
        except Exception as e2:
            logger.error(f"Критическая ошибка отправки сообщения: {e2}")
            await update.message.reply_text("❌ Произошла ошибка при отправке ответа.")

async def warmup_gemini_with_params(telegram_id: int, param_text: str):
    """
    Фоновый запрос к Gemini для инициализации с новыми параметрами
    Выполняется невидимо для пользователя
    """
    try:
        # Получаем API-ключ и модель пользователя
        api_key = key_manager.get_user_api_key(telegram_id)
        if not api_key:
            return
        
        model_name = db.get_user_model(telegram_id)
        gemini = GeminiClient(api_key, model_name)
        
        # Делаем простой запрос с параметрами для "разогрева"
        warmup_message = f"[Контекст пользователя: {param_text}]\n\nПривет, это тестовое сообщение."
        response = gemini.chat([{"role": "user", "content": warmup_message}])
        masked_id = f"***{str(telegram_id)[-4:]}" if telegram_id else "неизвестен"
        logger.info(f"Фоновый запрос для пользователя {masked_id} выполнен успешно")
    except Exception as e:
        masked_id = f"***{str(telegram_id)[-4:]}" if telegram_id else "неизвестен"
        logger.error(f"Ошибка фонового запроса для пользователя {masked_id}")
        # Не показываем ошибку пользователю, это фоновый процесс

async def params_command_callback(query, telegram_id: int):
    """Помощник для обновления списка параметров в callback"""
    parameters = db.get_user_parameters(telegram_id)
    
    if parameters:
        # Показываем только profile параметр (основной текст)
        params_text = parameters.get('profile', '')
        if not params_text:
            # Если profile нет, показываем все параметры
            params_text = " ".join([f"{key}: {value}" for key, value in parameters.items()])
        
        words = params_text.split()
        if len(words) > 40:
            params_text = " ".join(words[:40]) + "..."
        message_text = f"Ваши параметры: {params_text}"
    else:
        message_text = "Ваши параметры: не указаны"
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить/Изменить", callback_data="param_edit")],
    ]
    
    if parameters:
        keyboard.append([InlineKeyboardButton("🗑️ Очистить все", callback_data="param_clear_all")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message_text, reply_markup=reply_markup)

def is_image_generation_request(text: str) -> bool:
    """Проверяет, является ли запрос запросом на генерацию изображения"""
    if not text:
        return False
    
    text_lower = text.lower().strip()
    
    # Ключевые слова для генерации изображений
    generation_keywords = [
        # Русские варианты
        'сгенерируй',
        'сгенерируй изображение',
        'сгенерируй картинку',
        'сгенерируй фото',
        'создай изображение',
        'создай картинку',
        'создай фото',
        'сделай изображение',
        'сделай картинку',
        'сделай фото',
        'нарисуй',
        'генерируй',
        'создай',
        'сделай',
        # Английские варианты
        'generate',
        'generate image',
        'generate picture',
        'create image',
        'create picture',
        'create photo',
        'draw',
        'make image',
        'make picture'
    ]
    
    # Проверяем, начинается ли запрос с ключевого слова или содержит его
    for keyword in generation_keywords:
        if text_lower.startswith(keyword) or keyword in text_lower:
            return True
    
    return False

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    telegram_id = update.effective_user.id
    user_text = update.message.text
    
    # Обновляем время последней активности пользователя
    db.update_user_activity(telegram_id)
    
    try:
        # Проверяем, является ли это запросом на генерацию изображения
        if is_image_generation_request(user_text):
            # Получаем API ключ пользователя для прямой генерации
            api_key = key_manager.get_user_api_key(telegram_id)
            if not api_key:
                await update.message.reply_text("❌ Ошибка: сервис временно недоступен. Попробуйте позже.")
                return
            
            # Отправляем статус генерации
            status_msg = await update.message.reply_text("🎨 Генерирую контент (изображение и текст)...")
            
            # Получаем выбранную модель пользователя
            user_model_key = db.get_user_model(telegram_id)
            
            # Прямая генерация через модель для генерации изображений (без посредничества)
            try:
                text_response, generated_image = await generate_content_direct(api_key, user_text, None, user_model_key)
                
                await status_msg.delete()
                
                # Получаем или создаем чат для генерации изображений
                chat_id, chat = get_active_chat_for_user(telegram_id, context)
                if not chat_id:
                    # Создаем новый чат для генерации если нет активного
                    chat = db.create_chat(telegram_id, "Генерация изображений", "generation")
                    if chat:
                        chat_id = UUID(chat['chat_id'])
                        context.user_data['active_chat_id'] = str(chat_id)
                
                # Сохраняем запрос пользователя в БД ДО генерации
                if chat_id:
                    db.add_message(chat_id, "user", user_text, "generation_request")
                
                # Если есть изображение, отправляем его
                if generated_image:
                    image_buffer = BytesIO(generated_image)
                    image_buffer.name = 'generated_image.png'
                    
                    # Если есть текстовый ответ, добавляем в caption
                    caption = f"🎨 Изображение сгенерировано по запросу: {user_text}"
                    if text_response:
                        caption += f"\n\n{text_response[:500]}"  # Ограничиваем длину caption
                    
                    await update.message.reply_photo(
                        photo=InputFile(image_buffer, filename='generated_image.png'),
                        caption=caption
                    )
                    
                    # Сохраняем контекст генерации в БД (только текстовый ответ, без самого изображения)
                    context_text = f"Сгенерировано изображение по запросу: {user_text}"
                    if text_response:
                        context_text += f"\nОтвет модели: {text_response[:200]}"
                    db.add_message(chat_id, "model", context_text, "generation_response")
                    
                    # Обновляем краткое описание контекста чата
                    db.update_chat_context(chat_id, f"Последняя генерация: {user_text[:100]}")
                    
                    # Если текстовый ответ длинный, отправляем отдельным сообщением
                    if text_response and len(text_response) > 500:
                        await safe_send_message(update, text_response)
                
                # Если только текст без изображения
                elif text_response:
                    await safe_send_message(update, f"📝 Ответ:\n\n{text_response}")
                    
                    # Сохраняем ответ модели в БД
                    db.add_message(chat_id, "model", text_response, "generation_response")
                    
                    # Если не было изображения, но был запрос на генерацию - показываем информацию о miniapp
                    has_subscription = db.has_active_subscription(telegram_id)
                    trial_status = db.get_trial_status(telegram_id)
                    is_trial_active = trial_status.get('is_active', False)
                    
                    message_text = (
                        "🎨 **Генерация изображений доступна в Mini App**\n\n"
                        "Генерация изображений работает только через Mini App (веб-версию бота).\n\n"
                    )
                    
                    if has_subscription or is_trial_active:
                        message_text += (
                            "✅ У вас есть активная подписка.\n\n"
                            "📱 Откройте Mini App через кнопку меню в боте или используйте команду /app\n\n"
                            "В Mini App вы найдете раздел '🎨 Генерация изображений'."
                        )
                        keyboard = [
                            [InlineKeyboardButton("📱 Открыть Mini App", web_app=WebAppInfo(url=config.MINI_APP_URL))]
                        ]
                else:
                        message_text += (
                            "💎 **Требуется подписка**\n\n"
                            "Для использования генерации изображений нужна активная подписка.\n\n"
                            "Используйте команду /subscription для оформления подписки или /trial для пробного периода."
                        )
                        keyboard = [
                            [InlineKeyboardButton("💎 Оформить подписку", callback_data="sub_menu")],
                            [InlineKeyboardButton("🎁 Пробный период", callback_data="trial_activate")]
                        ]
                    
                await update.message.reply_text(
                    message_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                error_msg = str(e)
                error_lower = error_msg.lower()
                logger.error(f"Ошибка при прямой генерации: {e}", exc_info=True)
                
                # Специальная обработка ошибок квоты и лимитов
                if any(keyword in error_lower for keyword in ["quota", "429", "resource_exhausted", "limit", "превышен", "лимит"]):
                    # Извлекаем информацию о времени ожидания
                    import re
                    retry_match = re.search(r'retry.*?(\d+(?:\.\d+)?)\s*s', error_lower)
                    retry_seconds = int(float(retry_match.group(1))) if retry_match else None
                    
                    retry_text = f"\n\n⏰ Попробуйте снова через {retry_seconds} секунд." if retry_seconds else "\n\n⏰ Попробуйте позже (через несколько минут)."
                    
                    await status_msg.edit_text(
                        "⚠️ **Превышен лимит запросов для генерации изображений.**\n\n"
                        "Сервис временно недоступен из-за высокой нагрузки.\n\n"
                        "**Что можно сделать:**\n"
                        "• Подождите несколько минут перед повторной попыткой\n"
                        "• Попробуйте другой запрос\n"
                        f"{retry_text}"
                    )
                elif any(keyword in error_lower for keyword in ["safety", "blocked", "harmful", "policy violation", "content policy", "safety filter"]):
                    await status_msg.edit_text(
                        "🚫 **Запрос заблокирован.**\n\n"
                        "Ваш запрос был отклонен системой безопасности Gemini.\n\n"
                        "Попробуйте переформулировать запрос или использовать другие ключевые слова."
                    )
                else:
                    # Общая ошибка - показываем понятное сообщение
                    await status_msg.edit_text(
                        "❌ **Произошла ошибка при генерации изображения.**\n\n"
                        "К сожалению, не удалось сгенерировать изображение.\n\n"
                        "**Возможные причины:**\n"
                        "• Временная недоступность сервиса\n\n"
                        "Пожалуйста, попробуйте еще раз через несколько минут."
                    )
            return
        
        # Проверяем, ожидается ли ввод параметра
        if context.user_data.get('waiting_for_param'):
            param_text = user_text.strip()
            
            # Получаем существующие параметры для предварительного просмотра
            existing_params = db.get_user_parameters(update.effective_user.id)
            existing_text = existing_params.get('profile', '')
            
            # Объединяем для предварительного просмотра
            if existing_text:
                preview_text = f"{existing_text} {param_text}"
            else:
                preview_text = param_text
            
            # Проверяем количество слов
            words = preview_text.split()
            word_count = len(words)
            
            # Показываем предупреждение если больше 40, но не блокируем
            warning = ""
            if word_count > 40:
                warning = f"\n\n⚠️ Внимание: После добавления будет {word_count} слов (рекомендуется до 40). Лишние слова будут обрезаны."
                preview_text = " ".join(words[:40]) + "..."
            
            # Сохраняем во временный контекст
            context.user_data['param_text'] = param_text
            
            # Показываем кнопки сохранения/отмены
            keyboard = [
                [InlineKeyboardButton("💾 Сохранить", callback_data="param_save")],
                [InlineKeyboardButton("❌ Отменить", callback_data="param_cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            preview_display = f"📝 Текущие параметры:\n{existing_text if existing_text else '(пусто)'}\n\n➕ Новые параметры:\n{param_text}\n\n📋 Итого:\n{preview_text}{warning}"
            
            await update.message.reply_text(
                preview_display + "\n\nИспользуйте кнопки для сохранения или отмены.",
                reply_markup=reply_markup
            )
            return
        
        # Обычная обработка текста
        chat_id, chat = get_active_chat_for_user(telegram_id, context)
        if not chat_id:
            await update.message.reply_text("❌ Ошибка при получении чата.")
            return
        
        # Сохраняем сообщение пользователя (определяем тип: live или обычное)
        # Проверяем, является ли это live чатом (можно проверить по типу чата или модели)
        user_model = db.get_user_model(telegram_id)
        model_info = config.GEMINI_MODELS.get(user_model, {})
        is_live_chat = model_info.get('supports_voice', False)
        
        context_type = "live_message" if is_live_chat else None
        db.add_message(chat_id, "user", user_text, context_type)
        
        # Получаем историю сообщений для контекста (исключаем медиа-сообщения)
        # Медиа обрабатывается независимо и не должно влиять на текстовые ответы
        messages = db.get_chat_messages(chat_id, limit=config.CONTEXT_WINDOW_SIZE, exclude_media=True)
        
        # Получаем параметры пользователя для контекста
        user_params = db.get_user_parameters(telegram_id)
        
        # Формируем историю для Gemini (только role и content)
        # Убираем дубликаты по содержанию чтобы избежать повторений
        # Также проверяем последовательные дубликаты (одинаковые сообщения подряд)
        seen_contents = set()
        chat_history = []
        prev_content = None
        for msg in messages:
            content = msg['content']
            # Пропускаем дубликаты и последовательные одинаковые сообщения
            if content in seen_contents or content == prev_content:
                continue
            seen_contents.add(content)
            prev_content = content
            chat_history.append({"role": msg['role'], "content": content})
        
        # Добавляем параметры пользователя только если есть история или это первое сообщение
        if user_params:
            # Объединяем все параметры в один текст
            params_text = " ".join([f"{key}: {value}" for key, value in user_params.items()])
            
            if len(chat_history) > 0:
                # Добавляем параметры в последнее сообщение
                params_context = f"\n\n[Контекст пользователя: {params_text}]"
                chat_history[-1]['content'] = chat_history[-1]['content'] + params_context
            else:
                # Если истории нет, добавляем как отдельное системное сообщение
                chat_history.insert(0, {
                    "role": "user",
                    "content": f"[Контекст пользователя: {params_text}]"
                })
        
        # Отправляем статус обработки
        status_msg = await update.message.reply_text("💬 Обрабатываю ваш вопрос...")
        
        # Получаем API ключ для проверки голосовых моделей
        api_key = key_manager.get_user_api_key(telegram_id)
        
        # Получаем обработчики с правильным API-ключом
        user_handlers = get_handlers_for_user(telegram_id)
        
        # Получаем выбранную модель пользователя
        model_name = db.get_user_model(telegram_id)
        model_config = config.GEMINI_MODELS.get(model_name, config.GEMINI_MODELS[config.DEFAULT_MODEL])
        
        # Проверяем, поддерживает ли модель голосовые ответы
        supports_voice = model_config.get('supports_voice', False)
        
        # Получаем ответ от Gemini
        response = user_handlers.gemini.chat(chat_history, context_window=config.CONTEXT_WINDOW_SIZE)
        
        # Сохраняем ответ модели (с типом контекста если это live чат)
        response_context_type = "live_message" if is_live_chat else None
        db.add_message(chat_id, "model", response, response_context_type)
        
        # Обновляем краткое описание контекста чата для live общения
        if is_live_chat:
            context_summary = f"Последний запрос: {user_text[:50]}{'...' if len(user_text) > 50 else ''}"
            db.update_chat_context(chat_id, context_summary)
        
        # Удаляем статус
        await status_msg.delete()
        
        # Если модель поддерживает голос, генерируем и отправляем голосовой ответ
        if supports_voice and api_key:
            try:
                # Генерируем голосовой ответ через голосовую модель
                voice_data = await generate_voice_response(api_key, response, model_config['name'])
                
                if voice_data:
                    # Отправляем голосовое сообщение
                    voice_buffer = BytesIO(voice_data)
                    voice_buffer.name = 'response.ogg'
                    await update.message.reply_voice(
                        voice=InputFile(voice_buffer, filename='response.ogg'),
                        caption=response[:200] if len(response) > 200 else response  # Короткая подпись
                    )
                    return
            except Exception as e:
                logger.warning(f"Не удалось сгенерировать голосовой ответ: {e}, отправляем текстом")
        
        # Отправляем текстовый ответ с форматированием
        await safe_send_message(update, response)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке текста: {e}")
        await update.message.reply_text(
            f"❌ Произошла ошибка: {str(e)}"
        )

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик голосовых сообщений"""
    telegram_id = update.effective_user.id
    voice = update.message.voice
    
    try:
        # Получаем активный чат
        chat_id, chat = get_active_chat_for_user(telegram_id, context)
        if not chat_id:
            await update.message.reply_text("❌ Ошибка при получении чата.")
            return
        
        # Отправляем статус обработки
        status_msg = await update.message.reply_text("💬 Обрабатываю ваш вопрос...")
        
        # Скачиваем файл
        voice_file = await context.bot.get_file(voice.file_id)
        voice_path = f"temp_{voice.file_id}_{update.message.message_id}.ogg"
        await voice_file.download_to_drive(voice_path)
        
        try:
            # Получаем подпись если есть
            caption = update.message.caption
            
            # Получаем историю чата для контекста (исключаем медиа)
            messages = db.get_chat_messages(chat_id, limit=config.CONTEXT_WINDOW_SIZE, exclude_media=True)
            chat_history = [
                {"role": msg['role'], "content": msg['content']}
                for msg in messages
            ]
            
            # Получаем обработчики
            user_handlers = get_handlers_for_user(telegram_id)
            
            # Обрабатываем голос с историей чата
            response = await user_handlers.handle_voice(voice_path, caption, chat_history)
            
            # НЕ сохраняем медиа в историю БД - обрабатываем независимо
            # Медиа-сообщения не должны влиять на текстовые запросы
            # Это гарантирует, что следующее текстовое сообщение будет обрабатываться независимо
            
            # Удаляем статус и отправляем ответ с форматированием
            await status_msg.delete()
            await safe_send_message(update, response)
        finally:
            # Удаляем временный файл (гарантируем удаление)
            import os
            try:
                if os.path.exists(voice_path):
                    os.unlink(voice_path)
                    print(f"Временный файл удален: {voice_path}")
            except Exception as e:
                print(f"Ошибка при удалении временного файла {voice_path}: {e}")
                
    except Exception as e:
        logger.error(f"Ошибка при обработке голоса: {e}")
        await update.message.reply_text(
            f"❌ Произошла ошибка при обработке голосового сообщения: {str(e)}"
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик фотографий"""
    telegram_id = update.effective_user.id
    photo = update.message.photo[-1]  # Берем фото наибольшего размера
    
    try:
        # Получаем активный чат
        chat_id, chat = get_active_chat_for_user(telegram_id, context)
        if not chat_id:
            await update.message.reply_text("❌ Ошибка при получении чата.")
            return
        
        # Получаем подпись если есть
        caption = update.message.caption
        
        # Проверяем, является ли подпись запросом на генерацию изображения
        is_generation = caption and is_image_generation_request(caption)
        
        if is_generation:
            # Генерация изображения на основе фото и текста (прямая генерация)
            status_msg = await update.message.reply_text("🎨 Генерирую контент на основе фото...")
            
            # Получаем API ключ пользователя для прямой генерации
            api_key = key_manager.get_user_api_key(telegram_id)
            if not api_key:
                await status_msg.edit_text("❌ Ошибка: сервис временно недоступен. Попробуйте позже.")
                return
            
            # Скачиваем фото
            photo_file = await context.bot.get_file(photo.file_id)
            photo_data = await photo_file.download_as_bytearray()
            
            # Получаем или создаем чат для генерации изображений
            chat_id, chat = get_active_chat_for_user(telegram_id, context)
            if not chat_id:
                # Создаем новый чат для генерации если нет активного
                chat = db.create_chat(telegram_id, "Генерация изображений", "generation")
                if chat:
                    chat_id = UUID(chat['chat_id'])
                    context.user_data['active_chat_id'] = str(chat_id)
            
            # Формируем текст запроса
            request_text = caption if caption else "Создай изображение на основе этого фото"
            
            # Сохраняем запрос пользователя с описанием фото
            if chat_id:
                db.add_message(chat_id, "user", f"Генерация по фото: {request_text}", "generation_request")
            
            # Получаем выбранную модель пользователя
            user_model_key = db.get_user_model(telegram_id)
            
            # Прямая генерация через модель для генерации изображений с референсным изображением
            try:
                text_response, generated_image = await generate_content_direct(
                    api_key, 
                    request_text,
                    bytes(photo_data),
                    user_model_key
                )
                
                await status_msg.delete()
                
                # Если есть изображение, отправляем его
                if generated_image:
                    image_buffer = BytesIO(generated_image)
                    image_buffer.name = 'generated_image.png'
                    
                    # Если есть текстовый ответ, добавляем в caption
                    caption_text = f"🎨 Изображение сгенерировано на основе фото и запроса: {request_text}"
                    if text_response:
                        caption_text += f"\n\n{text_response[:500]}"
                    
                    await update.message.reply_photo(
                        photo=InputFile(image_buffer, filename='generated_image.png'),
                        caption=caption_text
                    )
                    
                    # Сохраняем контекст генерации в БД
                    if chat_id:
                        context_text = f"Сгенерировано изображение на основе фото и запроса: {request_text}"
                        if text_response:
                            context_text += f"\nОтвет модели: {text_response[:200]}"
                        db.add_message(chat_id, "model", context_text, "generation_response")
                        db.update_chat_context(chat_id, f"Последняя генерация: {request_text[:100]}")
                    
                    # Если текстовый ответ длинный, отправляем отдельным сообщением
                    if text_response and len(text_response) > 500:
                        await safe_send_message(update, text_response)
                
                # Если только текст без изображения
                elif text_response:
                    await safe_send_message(update, f"📝 Ответ:\n\n{text_response}")
                    
                    # Сохраняем ответ модели в БД
                    if chat_id:
                        db.add_message(chat_id, "model", text_response, "generation_response")
                    
                    # Если не было изображения, но был запрос на генерацию - показываем информацию о miniapp
                    has_subscription = db.has_active_subscription(telegram_id)
                    trial_status = db.get_trial_status(telegram_id)
                    is_trial_active = trial_status.get('is_active', False)
                    
                    message_text = (
                        "🎨 **Генерация изображений доступна в Mini App**\n\n"
                        "Генерация изображений работает только через Mini App (веб-версию бота).\n\n"
                    )
                    
                    if has_subscription or is_trial_active:
                        message_text += (
                            "✅ У вас есть активная подписка.\n\n"
                            "📱 Откройте Mini App через кнопку меню в боте или используйте команду /app\n\n"
                            "В Mini App вы найдете раздел '🎨 Генерация изображений'."
                        )
                        keyboard = [
                            [InlineKeyboardButton("📱 Открыть Mini App", web_app=WebAppInfo(url=config.MINI_APP_URL))]
                        ]
                else:
                        message_text += (
                            "💎 **Требуется подписка**\n\n"
                            "Для использования генерации изображений нужна активная подписка.\n\n"
                            "Используйте команду /subscription для оформления подписки или /trial для пробного периода."
                        )
                        keyboard = [
                            [InlineKeyboardButton("💎 Оформить подписку", callback_data="sub_menu")],
                            [InlineKeyboardButton("🎁 Пробный период", callback_data="trial_activate")]
                        ]
                    
                await update.message.reply_text(
                    message_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                error_msg = str(e)
                error_lower = error_msg.lower()
                logger.error(f"Ошибка при прямой генерации с фото: {e}", exc_info=True)
                
                # Специальная обработка ошибок квоты и лимитов
                if any(keyword in error_lower for keyword in ["quota", "429", "resource_exhausted", "limit", "превышен", "лимит"]):
                    # Извлекаем информацию о времени ожидания
                    import re
                    retry_match = re.search(r'retry.*?(\d+(?:\.\d+)?)\s*s', error_lower)
                    retry_seconds = int(float(retry_match.group(1))) if retry_match else None
                    
                    retry_text = f"\n\n⏰ Попробуйте снова через {retry_seconds} секунд." if retry_seconds else "\n\n⏰ Попробуйте позже (через несколько минут)."
                    
                    await status_msg.edit_text(
                        "⚠️ **Превышен лимит запросов для генерации изображений.**\n\n"
                        "Сервис временно недоступен из-за высокой нагрузки.\n\n"
                        "**Что можно сделать:**\n"
                        "• Подождите несколько минут перед повторной попыткой\n"
                        "• Попробуйте другой запрос\n"
                        f"{retry_text}"
                    )
                elif any(keyword in error_lower for keyword in ["safety", "blocked", "harmful", "policy violation", "content policy", "safety filter"]):
                    await status_msg.edit_text(
                        "🚫 **Запрос заблокирован.**\n\n"
                        "Ваш запрос был отклонен системой безопасности Gemini.\n\n"
                        "Попробуйте переформулировать запрос или использовать другие ключевые слова."
                    )
                else:
                    # Общая ошибка - показываем понятное сообщение
                    await status_msg.edit_text(
                        "❌ **Произошла ошибка при генерации изображения.**\n\n"
                        "К сожалению, не удалось сгенерировать изображение.\n\n"
                        "**Возможные причины:**\n"
                        "• Временная недоступность сервиса\n\n"
                        "Пожалуйста, попробуйте еще раз через несколько минут."
                    )
            return
        
        # Обычная обработка фото (анализ)
        # Отправляем статус обработки
        status_msg = await update.message.reply_text("💬 Запрос обрабатывается...")
        
        # Скачиваем фото
        photo_file = await context.bot.get_file(photo.file_id)
        photo_data = await photo_file.download_as_bytearray()
        
        # Сохраняем сообщение пользователя в БД (фото с подписью как одно сообщение)
        # Если есть подпись - используем её, если нет - указываем что отправлено фото
        user_message_text = caption if caption else "📷 [Фото]"
        db.add_message(chat_id, "user", user_message_text)
        
        # Получаем историю сообщений для контекста (исключаем медиа-сообщения)
        messages = db.get_chat_messages(chat_id, limit=config.CONTEXT_WINDOW_SIZE, exclude_media=True)
        
        # Формируем историю для Gemini (только role и content)
        seen_contents = set()
        chat_history = []
        prev_content = None
        for msg in messages:
            content = msg['content']
            # Пропускаем дубликаты и последовательные одинаковые сообщения
            if content in seen_contents or content == prev_content:
                continue
            seen_contents.add(content)
            prev_content = content
            chat_history.append({"role": msg['role'], "content": content})
        
        # Получаем обработчики
        user_handlers = get_handlers_for_user(telegram_id)
        
        # Обрабатываем фото с историей чата для контекста
        response = await user_handlers.handle_photo(bytes(photo_data), caption, chat_history)
        
        # Сохраняем ответ модели в БД
        db.add_message(chat_id, "model", response)
        
        # Удаляем статус и отправляем ответ с форматированием
        await status_msg.delete()
        await safe_send_message(update, response)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке фото: {e}")
        await update.message.reply_text(
            f"❌ Произошла ошибка при обработке фотографии: {str(e)}"
        )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик документов (PDF, TXT, аудио)"""
    telegram_id = update.effective_user.id
    document = update.message.document
    file_name = document.file_name.lower() if document.file_name else ""
    
    try:
        # Получаем активный чат
        chat_id, chat = get_active_chat_for_user(telegram_id, context)
        if not chat_id:
            await update.message.reply_text("❌ Ошибка при получении чата.")
            return
        
        # Отправляем статус обработки
        status_msg = await update.message.reply_text("💬 Запрос обрабатывается...")
        
        # Проверяем размер файла перед скачиванием
        if document.file_size and document.file_size > config.MAX_FILE_SIZE:
            await status_msg.delete()
            await update.message.reply_text(f"❌ Файл слишком большой ({document.file_size / 1024 / 1024:.1f} МБ). Максимум {config.MAX_FILE_SIZE / 1024 / 1024:.0f} МБ.")
            return
        
        # Скачиваем файл
        doc_file = await context.bot.get_file(document.file_id)
        file_path = f"temp_{document.file_id}_{update.message.message_id}_{document.file_name}"
        await doc_file.download_to_drive(file_path)
        
        try:
            # Получаем подпись если есть
            caption = update.message.caption
            
            # Получаем обработчики
            user_handlers = get_handlers_for_user(telegram_id)
            
            response = None
            
            # Определяем тип файла и обрабатываем
            if file_name.endswith('.pdf'):
                response = await user_handlers.handle_pdf(file_path, caption)
            elif file_name.endswith(('.txt', '.text')):
                response = await user_handlers.handle_text_file(file_path, caption)
            elif file_name.endswith(('.mp3', '.wav', '.ogg', '.m4a', '.flac')):
                response = await user_handlers.handle_audio_file(file_path, caption)
            else:
                response = "❌ Неподдерживаемый тип файла. Поддерживаются: PDF, TXT, аудио (MP3, WAV, OGG)."
            
            if response:
                # Удаляем статус и отправляем ответ с форматированием
                await status_msg.delete()
                try:
                    formatted_response = format_response_for_telegram(response)
                    await update.message.reply_text(formatted_response, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.warning(f"Ошибка форматирования: {e}")
                    await safe_send_message(update, response)
                
        finally:
            # Удаляем временный файл (гарантируем удаление)
            import os
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
                    print(f"Временный файл удален: {file_path}")
            except Exception as e:
                print(f"Ошибка при удалении временного файла {file_path}: {e}")
                
    except Exception as e:
        logger.error(f"Ошибка при обработке документа: {e}")
        await update.message.reply_text(
            f"❌ Произошла ошибка при обработке файла: {str(e)}"
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Глобальный обработчик ошибок"""
    error = context.error
    
    # Детальное логирование ошибки
    logger.error(f"❌ Ошибка при обработке обновления: {error}", exc_info=error)
    
    # Определяем тип ошибки для более информативного сообщения
    error_msg = str(error).lower() if error else ""
    
    user_message = "❌ Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже."
    
    if "timeout" in error_msg or "timed out" in error_msg:
        logger.warning("⚠️ Обнаружена ошибка таймаута (возможно, проблема с сетью или API)")
        user_message = "⏱️ Превышено время ожидания. Проверьте подключение к интернету и попробуйте снова."
    elif "network" in error_msg or "connection" in error_msg:
        logger.warning("⚠️ Обнаружена проблема с сетевым соединением")
        user_message = "🌐 Проблема с сетевым соединением. Проверьте интернет и попробуйте позже."
    elif "quota" in error_msg or "429" in error_msg:
        logger.warning("⚠️ Превышен лимит запросов к API")
        user_message = "⚠️ Превышен лимит запросов. Подождите немного и попробуйте снова."
    elif "401" in error_msg or "unauthorized" in error_msg:
        logger.warning("⚠️ Проблема с авторизацией (токен или API ключ)")
        user_message = "🔐 Проблема с авторизацией. Обратитесь к администратору."
    
    # Пытаемся отправить сообщение пользователю
    if update and update.message:
        try:
            await update.message.reply_text(user_message)
        except Exception as send_error:
            logger.error(f"❌ Не удалось отправить сообщение об ошибке пользователю: {send_error}")
    elif update and update.callback_query:
        try:
            await update.callback_query.answer("❌ Произошла ошибка", show_alert=True)
        except Exception as callback_error:
            logger.error(f"❌ Не удалось отправить ответ на callback: {callback_error}")

def start_bot():
    """Синхронная функция запуска бота"""
    # Создаем приложение
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("model", model_command))
    application.add_handler(CommandHandler("params", params_command))
    application.add_handler(CommandHandler("subscription", subscription_command))
    application.add_handler(CommandHandler("trial", trial_command))
    application.add_handler(CommandHandler("about", about_project_command))
    application.add_handler(CommandHandler("app", open_app_command))
    application.add_handler(CommandHandler("invite", invite_command))
    application.add_handler(CommandHandler("menu", menu_command))
    
    # Регистрируем обработчики callback
    application.add_handler(CallbackQueryHandler(model_callback, pattern="^model_"))
    application.add_handler(CallbackQueryHandler(params_callback, pattern="^param_"))
    application.add_handler(CallbackQueryHandler(subscription_callback, pattern="^(sub_|refund_|sub_menu|trial_activate)"))
    application.add_handler(CallbackQueryHandler(copy_referral_callback, pattern="^copy_ref_"))
    
    # Регистрируем обработчики платежей Telegram Stars
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    
    # Регистрируем обработчики сообщений
    # Сначала обрабатываем кнопки меню (до текстовых сообщений)
    application.add_handler(MessageHandler(filters.Regex("^(🤖 Модель|⚙️ Параметры|💎 Подписка|🎁 Пробный период|🎁 Пригласить друга|➕ Новый чат)$"), handle_menu_button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Глобальный обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Устанавливаем команды бота асинхронно в фоне (не блокирует запуск)
    async def setup_commands_async(app: Application):
        """Установка команд бота в фоновом режиме"""
        try:
            # Небольшая задержка для полной инициализации
            await asyncio.sleep(1.0)
            
            # Устанавливаем команды с коротким таймаутом
            try:
                await asyncio.wait_for(
                    app.bot.set_my_commands([
            BotCommand("start", "Запустить бота и зарегистрироваться"),
                        BotCommand("model", "Выбрать модель AI"),
                        BotCommand("params", "Настроить параметры"),
                        BotCommand("subscription", "💎 Управление подпиской"),
                        BotCommand("trial", "🎁 Пробный период"),
                        BotCommand("app", "📱 Открыть приложение"),
                        BotCommand("invite", "🎁 Пригласить друга"),
                        BotCommand("menu", "🔄 Обновить меню")
                    ]),
                    timeout=5.0  # Короткий таймаут 5 секунд
                )
                logger.info("✅ Команды бота установлены успешно")
            except asyncio.TimeoutError:
                logger.warning("⚠️ Таймаут при установке команд (не критично, бот работает)")
            except Exception as cmd_error:
                logger.warning(f"⚠️ Ошибка установки команд: {cmd_error} (не критично)")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка в setup_commands_async: {e} (не критично)")
    
    # Запускаем установку команд в фоне через post_init (не блокирует)
    async def post_init(app: Application):
        """Пост-инициализация бота (не блокирующая)"""
        # Запускаем установку команд в фоне, не ожидая завершения
        asyncio.create_task(setup_commands_async(app))
        logger.info("🔄 Установка команд запущена в фоновом режиме")
    
    application.post_init = post_init
    
    # Запускаем бота (run_polling сам управляет event loop и инициализацией)
    logger.info("🚀 Запуск бота...")
    logger.info("⏳ Инициализация polling...")
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            close_loop=False,
            drop_pending_updates=True,
            stop_signals=None  # Отключаем обработку сигналов для более быстрого запуска
        )
    except RuntimeError as e:
        if "not properly initialized" in str(e):
            import telegram
            logger.error("Ошибка инициализации бота. Возможна проблема с версией python-telegram-bot.")
            logger.error(f"Текущая версия: {telegram.__version__}")
            logger.error("Попробуйте: pip install --upgrade python-telegram-bot")
        raise

def run_flask() -> None:
    """Запуск легковесного Flask приложения, требуемого для хоста Render"""
    import os
    from flask import Flask, send_from_directory, request, jsonify
    from pathlib import Path
    import json
    
    print("[flask] запуск вспомогательного веб-сервера...")
    
    app = Flask(__name__)
    
    # Путь к папке mini_app
    mini_app_dir = Path(__file__).parent / 'mini_app'
    
    @app.route("/")
    def home() -> tuple[str, int]:
        """Главная страница - простая фраза"""
        return "привет", 200
    
    @app.route("/health")
    def health() -> tuple[str, int]:
        """Health check endpoint для Render"""
        return "Telegram Bot is running (long polling in main thread).", 200
    
    @app.after_request
    def after_request(response):
        """Добавляем CORS заголовки для работы Mini App"""
        # Разрешаем все источники (в продакшене можно ограничить)
        origin = request.headers.get('Origin')
        if origin:
            response.headers.add('Access-Control-Allow-Origin', origin)
        else:
            response.headers.add('Access-Control-Allow-Origin', '*')
        
        # Полный набор заголовков для CORS
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With')
        response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, PUT, DELETE, PATCH')
        response.headers.add('Access-Control-Max-Age', '3600')
        return response
    
    @app.route("/api/user/data", methods=["POST", "OPTIONS"])
    def api_user_data():
        """API endpoint для получения данных пользователя из Supabase"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json or {}
            telegram_id = data.get('telegram_id')
            
            if not telegram_id:
                return jsonify({"error": "Missing telegram_id"}), 400
            
            # Получаем данные пользователя из Supabase
            user = db.get_user(telegram_id)
            
            if not user:
                # Если пользователя нет, возвращаем только базовые данные
                return jsonify({
                    "user": None,
                    "exists": False
                }), 200
            
            # Возвращаем данные пользователя (включая данные профиля)
            return jsonify({
                "user": {
                    "telegram_id": user.get('telegram_id'),
                    "model_name": user.get('model_name'),
                    "active_key_id": user.get('active_key_id'),
                    "username": user.get('username'),
                    "first_name": user.get('first_name'),
                    "photo_url": user.get('photo_url')
                },
                "exists": True
            }), 200
            
        except Exception as e:
            logger.error(f"[API User Data] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/user/referral", methods=["POST", "OPTIONS"])
    def api_user_referral():
        """API endpoint для получения referral кода пользователя"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json or {}
            telegram_id = data.get('telegram_id')
            
            if not telegram_id:
                return jsonify({"error": "Missing telegram_id"}), 400
            
            try:
                telegram_id = int(telegram_id)
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid telegram_id"}), 400
            
            referral_code = db.get_referral_code(telegram_id)
            
            # Получаем username бота из токена или используем дефолтный
            bot_username = getattr(config, 'TELEGRAM_BOT_USERNAME', None)
            if not bot_username:
                # Пробуем получить из application
                try:
                    from telegram import Bot
                    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
                    bot_info = bot.get_me()
                    bot_username = bot_info.username
                except:
                    bot_username = 'YOUR_BOT_USERNAME'  # Fallback
            
            invite_url = f"https://t.me/{bot_username}?start={referral_code}" if bot_username else None
            
            return jsonify({
                "referral_code": referral_code,
                "invite_url": invite_url
            }), 200
            
        except Exception as e:
            logger.error(f"[API User Referral] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/user/status", methods=["GET", "POST", "OPTIONS"])
    def api_user_status():
        """API endpoint для получения профиля пользователя и статуса подписки"""
        if request.method == 'OPTIONS':
            return '', 200
        
        # Поддержка GET метода для получения telegram_id из query параметров
        if request.method == 'GET':
            telegram_id = request.args.get('telegram_id')
            if telegram_id:
                try:
                    telegram_id = int(telegram_id)
                    # Получаем данные пользователя из БД напрямую
                    user = db.get_user(telegram_id)
                    if not user:
                        return jsonify({
                            "error": "User not found. Please activate the bot first with /start command.",
                            "user_not_found": True,
                            "telegram_id": telegram_id
                        }), 404
                    
                    # Возвращаем базовые данные
                    return jsonify({
                        "user": {
                            "telegram_id": telegram_id,
                            "first_name": user.get('first_name') or "Пользователь",
                            "username": user.get('username'),
                            "photo_url": user.get('photo_url')
                        }
                    }), 200
                except (ValueError, TypeError):
                    return jsonify({"error": "Invalid telegram_id"}), 400
            else:
                return jsonify({"error": "Missing telegram_id parameter"}), 400
        
        try:
            data = request.json or {}
            init_data = data.get('initData') or data.get('init_data')
            telegram_id = data.get('telegram_id')
            
            # ВАЛИДАЦИЯ initData (безопасность)
            user_data_from_init = None
            if init_data:
                user_data_from_init = validate_telegram_init_data(init_data, config.TELEGRAM_BOT_TOKEN)
                if user_data_from_init:
                    telegram_id = user_data_from_init.get('id', telegram_id)
                    logger.info(f"[API User Status] ✅ Валидация initData прошла, telegram_id: {telegram_id}")
                else:
                    logger.warning("[API User Status] ⚠️ Валидация initData не прошла, используем telegram_id из запроса")
            
            # Если нет telegram_id ни из initData, ни из запроса, пробуем парсить initData вручную (fallback)
            if not telegram_id and init_data:
                try:
                    from urllib.parse import unquote, parse_qs
                    params = parse_qs(init_data)
                    if 'user' in params and params['user']:
                        user_str = unquote(params['user'][0])
                        import json
                        user_obj = json.loads(user_str)
                        telegram_id = user_obj.get('id')
                        if telegram_id:
                            logger.info(f"[API User Status] ✅ Telegram ID получен через fallback парсинг initData: {telegram_id}")
                except Exception as e:
                    logger.warning(f"[API User Status] ⚠️ Fallback парсинг initData не удался: {e}")
            
            if not telegram_id:
                logger.error("[API User Status] ❌ Не удалось получить telegram_id ни из initData, ни из запроса")
                return jsonify({
                    "error": "Missing telegram_id or invalid initData",
                    "message": "Необходимо активировать бота через /start или предоставить валидный initData"
                }), 400
            
            try:
                telegram_id = int(telegram_id)
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid telegram_id"}), 400
            
            # Получаем данные пользователя из БД
            user = db.get_user(telegram_id)
            
            # Получаем данные из initData если они доступны (приоритет)
            first_name = None
            username = None
            photo_url = None
            
            if user_data_from_init:
                first_name = user_data_from_init.get('first_name')
                username = user_data_from_init.get('username')
                photo_url = user_data_from_init.get('photo_url')
            
            # Если пользователя нет в БД, значит он еще не активировал бота - возвращаем ошибку
            if not user:
                logger.warning(f"[API User Status] ⚠️ Пользователь {telegram_id} не найден в БД. Нужно сначала активировать бота через /start")
                return jsonify({
                    "error": "User not found. Please activate the bot first with /start command.",
                    "user_not_found": True,
                    "telegram_id": telegram_id
                }), 404
            
            # Используем данные из БД как fallback
            if not first_name:
                first_name = user.get('first_name')
            if not username:
                username = user.get('username')
            if not photo_url:
                photo_url = user.get('photo_url')
            
            # ВСЕГДА обновляем профиль если данные из initData доступны или если в БД нет username/first_name
            should_update = False
            if user_data_from_init:
                should_update = True  # Данные из initData - всегда обновляем
            elif not user.get('first_name') or not user.get('username'):
                should_update = True  # В БД нет данных - нужно добавить
            
            # Если есть photo_url из initData (Telegram CDN), проверяем и скачиваем аватар
            server_photo_url = photo_url
            if photo_url and user_data_from_init and photo_url.startswith('https://'):
                # Проверяем, есть ли уже сохраненный файл
                extensions = ['jpg', 'jpeg', 'png', 'webp']
                avatar_exists = False
                for ext in extensions:
                    test_path = os.path.join(AVATARS_DIR, f"{telegram_id}.{ext}")
                    if os.path.exists(test_path):
                        server_photo_url = f"/api/avatar/{telegram_id}"
                        avatar_exists = True
                        break
                
                # Если файла нет, скачиваем в фоне
                if not avatar_exists:
                    def download_avatar_sync():
                        try:
                            import requests
                            response = requests.get(photo_url, timeout=10)
                            if response.status_code == 200:
                                # Определяем расширение
                                content_type = response.headers.get('Content-Type', 'image/jpeg')
                                ext = 'jpg'
                                if 'png' in content_type:
                                    ext = 'png'
                                elif 'webp' in content_type:
                                    ext = 'webp'
                                
                                # Сохраняем файл
                                filename = f"{telegram_id}.{ext}"
                                filepath = os.path.join(AVATARS_DIR, filename)
                                
                                with open(filepath, 'wb') as f:
                                    f.write(response.content)
                                
                                logger.info(f"[Avatar] Аватар скачан и сохранен для пользователя {telegram_id}")
                        except Exception as e:
                            logger.warning(f"[Avatar] Ошибка скачивания аватара: {e}")
                    
                    # Запускаем в отдельном потоке (не блокируем ответ)
                    threading.Thread(target=download_avatar_sync, daemon=True).start()
            
            # Если photo_url уже путь сервера, оставляем как есть
            if photo_url and photo_url.startswith('/api/avatar/'):
                server_photo_url = photo_url
            
            if should_update and (first_name or username or server_photo_url):
                db.update_user_profile(telegram_id, username=username, first_name=first_name, photo_url=server_photo_url)
                masked_id = f"***{str(telegram_id)[-4:]}" if telegram_id else "неизвестен"
                logger.info(f"[API User Status] ✅ Профиль пользователя обновлен: {masked_id}")
            
            # Обновляем photo_url в ответе на серверный путь если есть сохраненный файл
            final_photo_url = photo_url
            if photo_url and photo_url.startswith('https://'):
                # Проверяем наличие на сервере
                extensions = ['jpg', 'jpeg', 'png', 'webp']
                for ext in extensions:
                    test_path = os.path.join(AVATARS_DIR, f"{telegram_id}.{ext}")
                    if os.path.exists(test_path):
                        final_photo_url = f"/api/avatar/{telegram_id}"
                        break
            elif photo_url and photo_url.startswith('/api/avatar/'):
                final_photo_url = photo_url
            
            # Получаем статус подписки
            has_sub = db.has_active_subscription(telegram_id, username)
            subscription = db.get_active_subscription(telegram_id) if has_sub else None
            
            # Получаем статус пробного периода
            trial_status = db.get_trial_status(telegram_id)
            is_trial_active = trial_status.get('is_active', False)
            
            # Формируем ответ - пробный период считается как активная подписка
            response_data = {
                "user": {
                    "telegram_id": telegram_id,
                    "first_name": first_name or "Пользователь",
                    "username": username,
                    "photo_url": final_photo_url
                },
                "subscription": {
                    "has_subscription": has_sub or is_trial_active,
                    "is_active": False,
                    "is_trial": False,
                    "days_left": 0,
                    "hours_left": 0,
                    "end_date": None,
                    "type": None
                },
                "trial": trial_status
            }
            
            # ПРИОРИТЕТ: Сначала проверяем обычную подписку, потом trial
            # Если есть обычная подписка - возвращаем её, иначе возвращаем trial (если активен)
            if subscription:
                from datetime import datetime, timezone, timedelta
                try:
                    end_date = datetime.fromisoformat(subscription['end_date'].replace('Z', '+00:00'))
                    start_date = datetime.fromisoformat(subscription['start_date'].replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    days_left = max(0, (end_date - now).days) if end_date > now else 0
                    hours_left = max(0, (end_date - now).total_seconds() / 3600) if end_date > now else 0
                    
                    # Вычисляем сколько времени было добавлено из trial
                    # Проверяем, был ли trial активен в момент создания подписки
                    trial_hours_added = 0
                    user = db.get_user(telegram_id)
                    if user:
                        trial_start = user.get('trial_start')
                        trial_used = user.get('trial_used', False)
                        
                        # Если trial был использован при создании подписки, вычисляем сколько часов было добавлено
                        if trial_used and trial_start:
                            try:
                                if isinstance(trial_start, str):
                                    import dateutil.parser
                                    trial_start_dt = dateutil.parser.parse(trial_start)
                                else:
                                    trial_start_dt = trial_start
                                
                                if trial_start_dt.tzinfo is None:
                                    trial_start_dt = trial_start_dt.replace(tzinfo=timezone.utc)
                                
                                # Проверяем, что trial был активен когда создавалась подписка
                                # Trial длится 24 часа, но к подписке могло быть добавлено только остаток
                                trial_end = trial_start_dt + timedelta(hours=24)
                                
                                # Если подписка начиналась во время активного trial
                                if start_date <= trial_end:
                                    # Вычисляем сколько часов trial оставалось на момент создания подписки
                                    if start_date >= trial_start_dt:
                                        trial_hours_added = (trial_end - start_date).total_seconds() / 3600
                                    else:
                                        # Если подписка началась до trial (не должно быть, но на всякий случай)
                                        trial_hours_added = 24
                                    trial_hours_added = max(0, min(24, trial_hours_added))
                            except Exception as e:
                                logger.warning(f"Ошибка вычисления trial_hours_added: {e}")
                                trial_hours_added = 0
                    
                    response_data["subscription"] = {
                        "has_subscription": True,
                        "is_active": subscription.get('is_active', False) and end_date > now,
                        "is_trial": False,
                        "days_left": days_left,
                        "hours_left": round(hours_left, 1),
                        "end_date": subscription.get('end_date'),
                        "type": subscription.get('subscription_type'),
                        "trial_hours_added": trial_hours_added  # Сколько часов из пробного периода было добавлено
                    }
                except Exception as e:
                    logger.warning(f"Ошибка парсинга даты подписки: {e}")
                    response_data["subscription"] = {
                        "has_subscription": True,
                        "is_active": subscription.get('is_active', False),
                        "is_trial": False,
                        "days_left": 0,
                        "end_date": subscription.get('end_date'),
                        "type": subscription.get('subscription_type')
                    }
            elif is_trial_active:
                # Если нет обычной подписки, но есть активный trial - возвращаем trial
                hours_remaining = trial_status.get('hours_remaining', 0)
                days_remaining = max(0, int(hours_remaining / 24))
                hours_left = max(0, int(hours_remaining % 24))
                
                from datetime import datetime, timezone, timedelta
                now = datetime.now(timezone.utc)
                trial_end_date = now + timedelta(hours=hours_remaining)
                
                response_data["subscription"] = {
                    "has_subscription": True,
                    "is_active": True,
                    "is_trial": True,
                    "days_left": days_remaining,
                    "hours_left": round(hours_remaining, 1),
                    "end_date": trial_end_date.isoformat(),
                    "type": "trial",
                    "trial_hours_remaining": hours_remaining
                }
            
            return jsonify(response_data), 200
            
        except Exception as e:
            logger.error(f"[API User Status] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/avatar/<int:telegram_id>", methods=["GET"])
    def api_get_avatar(telegram_id):
        """
        Получение аватара пользователя по telegram_id
        """
        try:
            # Ищем файл аватара в папке avatars
            # Пробуем разные расширения
            extensions = ['jpg', 'jpeg', 'png', 'webp']
            avatar_path = None
            content_type = 'image/jpeg'
            
            for ext in extensions:
                test_path = os.path.join(AVATARS_DIR, f"{telegram_id}.{ext}")
                if os.path.exists(test_path):
                    avatar_path = test_path
                    if ext == 'png':
                        content_type = 'image/png'
                    elif ext == 'webp':
                        content_type = 'image/webp'
                    break
            
            if not avatar_path or not os.path.exists(avatar_path):
                logger.warning(f"[Avatar API] Аватар не найден для пользователя {telegram_id}")
                # Возвращаем 404
                from flask import abort
                return abort(404)
            
            # Отправляем файл
            from flask import send_from_directory
            return send_from_directory(
                AVATARS_DIR,
                os.path.basename(avatar_path),
                mimetype=content_type
            )
            
        except Exception as e:
            logger.error(f"[Avatar API] Ошибка получения аватара: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/admin/stats", methods=["POST", "OPTIONS"])
    def api_admin_stats():
        """API endpoint для получения статистики админки"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json or {}
            password = data.get('password')
            
            # Простая проверка пароля (пока hardcoded, потом из Supabase)
            if password != '240123':
                return jsonify({"error": "Invalid password"}), 401
            
            # Получаем статистику
            total_users = db.get_all_users_count()
            active_keys_count = db.get_active_keys_count()
            trial_active_count = db.get_active_trials_count()
            subscribed_count = db.get_subscribed_users_count()
            
            return jsonify({
                "total_users": total_users,
                "active_keys": active_keys_count,
                "trial_active": trial_active_count,
                "subscribed": subscribed_count
            }), 200
            
        except Exception as e:
            logger.error(f"[API Admin Stats] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/admin/subscription/create", methods=["POST", "OPTIONS"])
    def api_admin_create_subscription():
        """API endpoint для создания/продления подписки администратором"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json or {}
            password = data.get('password')
            telegram_id = data.get('telegram_id')
            subscription_type = data.get('subscription_type')  # '1_month', '3_months', '6_months'
            months = data.get('months')  # Опционально, кастомное количество месяцев
            
            # Проверка пароля
            if password != '240123':
                return jsonify({"error": "Invalid password"}), 401
            
            if not telegram_id or not subscription_type:
                return jsonify({"error": "Missing telegram_id or subscription_type"}), 400
            
            telegram_id = int(telegram_id)
            
            # Создаем/продлеваем подписку
            subscription = db.admin_create_subscription(telegram_id, subscription_type, months)
            
            if subscription:
                return jsonify({
                    "success": True,
                    "subscription": subscription
                }), 200
            else:
                logger.error(f"[API Admin Create Subscription] Подписка не создана для пользователя {telegram_id}")
                return jsonify({"error": "Failed to create subscription. Check server logs for details."}), 500
                
        except Exception as e:
            logger.error(f"[API Admin Create Subscription] Ошибка: {e}", exc_info=True)
            import traceback
            logger.error(f"[API Admin Create Subscription] Traceback: {traceback.format_exc()}")
            return jsonify({"error": f"Internal server error: {str(e)}"}), 500
    
    @app.route("/api/admin/subscription/pause", methods=["POST", "OPTIONS"])
    def api_admin_pause_subscription():
        """API endpoint для приостановки подписки"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json or {}
            password = data.get('password')
            telegram_id = data.get('telegram_id')
            
            if password != '240123':
                return jsonify({"error": "Invalid password"}), 401
            
            if not telegram_id:
                return jsonify({"error": "Missing telegram_id"}), 400
            
            telegram_id = int(telegram_id)
            
            result = db.pause_subscription(telegram_id)
            
            return jsonify({"success": result}), 200
            
        except Exception as e:
            logger.error(f"[API Admin Pause Subscription] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/admin/subscription/resume", methods=["POST", "OPTIONS"])
    def api_admin_resume_subscription():
        """API endpoint для возобновления подписки"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json or {}
            password = data.get('password')
            telegram_id = data.get('telegram_id')
            
            if password != '240123':
                return jsonify({"error": "Invalid password"}), 401
            
            if not telegram_id:
                return jsonify({"error": "Missing telegram_id"}), 400
            
            telegram_id = int(telegram_id)
            
            result = db.resume_subscription(telegram_id)
            
            return jsonify({"success": result}), 200
            
        except Exception as e:
            logger.error(f"[API Admin Resume Subscription] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/admin/subscription/stop", methods=["POST", "OPTIONS"])
    def api_admin_stop_subscription():
        """API endpoint для остановки подписки"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json or {}
            password = data.get('password')
            telegram_id = data.get('telegram_id')
            
            if password != '240123':
                return jsonify({"error": "Invalid password"}), 401
            
            if not telegram_id:
                return jsonify({"error": "Missing telegram_id"}), 400
            
            telegram_id = int(telegram_id)
            
            result = db.deactivate_subscription(telegram_id)
            
            return jsonify({"success": result}), 200
            
        except Exception as e:
            logger.error(f"[API Admin Stop Subscription] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/admin/users/list", methods=["POST", "OPTIONS"])
    def api_admin_users_list():
        """API endpoint для получения списка всех пользователей"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json or {}
            password = data.get('password')
            limit = data.get('limit', 1000)
            offset = data.get('offset', 0)
            
            if password != '240123':
                return jsonify({"error": "Invalid password"}), 401
            
            users = db.get_all_users_list(limit=limit, offset=offset)
            
            # Форматируем для админки
            formatted_users = []
            for user in users:
                formatted_users.append({
                    "telegram_id": user.get('telegram_id'),
                    "username": user.get('username') or '—',
                    "first_name": user.get('first_name') or '—',
                    "trial_used": user.get('trial_used', False)
                })
            
            return jsonify({
                "users": formatted_users,
                "count": len(formatted_users)
            }), 200
            
        except Exception as e:
            logger.error(f"[API Admin Users List] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/admin/users/search", methods=["POST", "OPTIONS"])
    def api_admin_users_search():
        """API endpoint для поиска пользователя"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json or {}
            password = data.get('password')
            search_term = data.get('search_term')
            
            if password != '240123':
                return jsonify({"error": "Invalid password"}), 401
            
            if not search_term:
                return jsonify({"error": "Missing search_term"}), 400
            
            user = db.search_user_by_id_or_username(search_term)
            
            if not user:
                return jsonify({"found": False}), 200
            
            # Получаем подписки пользователя
            subscriptions = db.get_user_subscriptions(user.get('telegram_id'))
            
            # Получаем активную подписку
            active_subscription = db.get_active_subscription(user.get('telegram_id'))
            
            # Получаем статус пробного периода
            trial_status = db.get_trial_status(user.get('telegram_id'))
            
            # Формируем детальную информацию
            user_info = {
                "telegram_id": user.get('telegram_id'),
                "username": user.get('username'),
                "first_name": user.get('first_name'),
                "photo_url": user.get('photo_url'),
                "trial_status": trial_status,
                "active_subscription": None,
                "all_subscriptions": subscriptions
            }
            
            if active_subscription:
                from datetime import datetime, timezone, timedelta
                try:
                    end_date = datetime.fromisoformat(active_subscription['end_date'].replace('Z', '+00:00'))
                    start_date = datetime.fromisoformat(active_subscription['start_date'].replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    days_left = max(0, (end_date - now).days)
                    hours_left = max(0, (end_date - now).total_seconds() / 3600)
                    
                    # Вычисляем trial_hours_added
                    trial_hours_added = 0
                    trial_start = user.get('trial_start')
                    trial_used = user.get('trial_used', False)
                    
                    if trial_used and trial_start:
                        try:
                            import dateutil.parser
                            
                            if isinstance(trial_start, str):
                                trial_start_dt = dateutil.parser.parse(trial_start)
                            else:
                                trial_start_dt = trial_start
                            
                            if trial_start_dt.tzinfo is None:
                                trial_start_dt = trial_start_dt.replace(tzinfo=timezone.utc)
                            
                            trial_end = trial_start_dt + timedelta(hours=24)
                            
                            # Если подписка начиналась во время активного trial
                            if start_date <= trial_end and start_date >= trial_start_dt:
                                trial_hours_added = (trial_end - start_date).total_seconds() / 3600
                                trial_hours_added = max(0, min(24, trial_hours_added))
                        except Exception as e:
                            logger.warning(f"Ошибка вычисления trial_hours_added в админке: {e}")
                    
                    user_info["active_subscription"] = {
                        "subscription_id": active_subscription.get('subscription_id') or active_subscription.get('id'),
                        "type": active_subscription.get('subscription_type'),
                        "start_date": active_subscription.get('start_date'),
                        "end_date": active_subscription.get('end_date'),
                        "is_active": active_subscription.get('is_active', False),
                        "days_left": days_left,
                        "hours_left": round(hours_left, 1),
                        "payment_charge_id": active_subscription.get('payment_charge_id'),  # Для Stars
                        "is_stars_payment": active_subscription.get('payment_charge_id') is not None,
                        "usage_percent": active_subscription.get('usage_percent'),  # % использования
                        "refund_percent": active_subscription.get('refund_percent'),  # % возможного возврата
                        "trial_hours_added": trial_hours_added  # Сколько часов из пробного периода было добавлено
                    }
                except Exception as e:
                    logger.warning(f"Ошибка парсинга подписки: {e}")
                    user_info["active_subscription"] = active_subscription
            
            return jsonify({
                "found": True,
                "user": user_info
            }), 200
            
        except Exception as e:
            logger.error(f"[API Admin Users Search] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/user/subscription", methods=["POST", "OPTIONS"])
    def api_user_subscription():
        """API endpoint для получения статуса подписки пользователя (legacy, используйте /api/user/status)"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json or {}
            telegram_id = data.get('telegram_id')
            username = data.get('username')  # Опционально, для проверки @rusolnik
            
            if not telegram_id:
                return jsonify({"error": "Missing telegram_id"}), 400
            
            # Проверяем подписку
            has_sub = db.has_active_subscription(telegram_id, username)
            subscription = db.get_active_subscription(telegram_id) if has_sub else None
            
            # Формируем ответ
            response_data = {
                "has_subscription": has_sub,
                "subscription": None
            }
            
            if subscription:
                from datetime import datetime, timezone
                try:
                    end_date = datetime.fromisoformat(subscription['end_date'].replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    days_left = (end_date - now).days if end_date > now else 0
                    
                    response_data["subscription"] = {
                        "type": subscription.get('subscription_type'),
                        "end_date": subscription.get('end_date'),
                        "days_left": days_left,
                        "is_active": subscription.get('is_active', False),
                        "auto_renew": subscription.get('auto_renew', False)
                    }
                except Exception as e:
                    logger.warning(f"Ошибка парсинга даты подписки: {e}")
                    response_data["subscription"] = {
                        "type": subscription.get('subscription_type'),
                        "is_active": subscription.get('is_active', False)
                    }
            
            return jsonify(response_data), 200
            
        except Exception as e:
            logger.error(f"[API Subscription] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/gemini/api-key", methods=["POST", "OPTIONS"])
    def api_gemini_api_key():
        """API endpoint для получения API ключа пользователя (для Live API)
        Автоматически назначает ключ с проверкой лимита (макс 5 пользователей на ключ)
        Требует валидации initData от Telegram WebApp для безопасности
        """
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json or {}
            init_data = data.get('initData') or data.get('init_data')
            telegram_id = data.get('telegram_id')
            
            # ВАЛИДАЦИЯ initData (безопасность)
            if init_data:
                logger.info("[API Key] Проверка валидации initData...")
                user_data = validate_telegram_init_data(init_data, config.TELEGRAM_BOT_TOKEN)
                
                if not user_data:
                    logger.error("[API Key] ❌ Валидация initData не прошла")
                    return jsonify({
                        "error": "Invalid or missing initData. Request must be from authorized Telegram WebApp.",
                        "success": False
                    }), 401
                
                # Используем telegram_id из валидированных данных
                validated_telegram_id = user_data.get('id')
                if validated_telegram_id:
                    telegram_id = validated_telegram_id
                    masked_validated_id = f"***{str(validated_telegram_id)[-4:]}"
                    logger.info(f"[API Key] ✅ telegram_id получен из валидированного initData: {masked_validated_id}")
            else:
                # Если initData не предоставлен, но telegram_id есть - выдаем предупреждение
                # Для обратной совместимости разрешаем, но логируем предупреждение
                logger.warning("[API Key] ⚠️ initData не предоставлен! Используется небезопасный режим.")
                if not telegram_id:
                    logger.error("[API Key] ❌ Отсутствует и initData, и telegram_id")
                    return jsonify({
                        "error": "Missing required parameter: initData (or telegram_id for backward compatibility)",
                        "success": False
                    }), 400
            
            if not telegram_id:
                logger.error(f"[API Key] Отсутствует telegram_id в запросе")
                return jsonify({"error": "Missing telegram_id"}), 400
            
            # Преобразуем в int если нужно
            try:
                telegram_id = int(telegram_id)
            except (ValueError, TypeError):
                logger.error(f"[API Key] Неверный тип telegram_id: {type(telegram_id).__name__}")
                return jsonify({"error": f"Invalid telegram_id type: {type(telegram_id).__name__}. Expected int."}), 400
            
            # Маскируем telegram_id в логах
            masked_id = f"***{str(telegram_id)[-4:]}" if telegram_id else "неизвестен"
            logger.info(f"[API Key] Запрос API ключа для пользователя: {masked_id}")
            
            # Проверяем пробный период перед выдачей ключа
            trial_status = db.get_trial_status(telegram_id)
            is_trial_active = trial_status.get('is_active', False)
            can_use_trial = trial_status.get('can_use', False)
            hours_remaining = trial_status.get('hours_remaining')
            
            if is_trial_active:
                logger.info(f"[Trial] ✅ Пробный период активен для пользователя: {masked_id}, осталось: {hours_remaining} часов")
            elif can_use_trial:
                logger.info(f"[Trial] ⚠️ Пробный период еще не активирован для пользователя: {masked_id}")
            else:
                trial_used = trial_status.get('trial_used', False)
                logger.info(f"[Trial] Пробный период {'использован' if trial_used else 'недоступен'} для пользователя: {masked_id}")
            
            # Обновляем время последней активности пользователя
            db.update_user_activity(telegram_id)
            
            # Получаем API ключ пользователя
            api_key = key_manager.get_user_api_key(telegram_id)
            has_key = api_key is not None
            key_length = len(api_key) if api_key else 0
            logger.info(f"[API Key] Ключ в БД: {'найден' if has_key else 'не найден'}, длина: {key_length}")
            
            # Если ключа нет, назначаем новый (с проверкой лимита через get_available_key)
            if not api_key:
                logger.info(f"[API Key] Назначаем новый ключ для пользователя: {masked_id}")
                try:
                    # Получаем данные пользователя из initData для сохранения в БД
                    # Если initData нет, пробуем получить из запроса
                    username = None
                    first_name = None
                    photo_url = None
                    
                    # Пробуем получить из initData
                    if init_data:
                        user_data = validate_telegram_init_data(init_data, config.TELEGRAM_BOT_TOKEN)
                        if user_data:
                            username = user_data.get('username')
                            first_name = user_data.get('first_name')
                            photo_url = user_data.get('photo_url')
                    
                    key_id, api_key, status = key_manager.assign_key_to_user(telegram_id, 
                                                                           username=username, 
                                                                           first_name=first_name, 
                                                                           photo_url=photo_url)
                    key_status = "получен" if api_key else "не получен"
                    masked_new_key = f"***{api_key[-4:]}" if api_key else "отсутствует"
                    logger.info(f"[API Key] Назначение ключа: {key_status}, статус: {status}, ключ: {masked_new_key}")
                    
                    if not api_key:
                        # Проверяем причины
                        all_keys = key_manager.db.get_all_api_keys()
                        active_keys = [k for k in all_keys if k.get('is_active')]
                        logger.error(f"[API Key] Нет доступных ключей. Всего: {len(all_keys)}, активных: {len(active_keys)}")
                        
                        return jsonify({
                            "error": "No available API keys. All keys have reached the maximum user limit (5 users per key)."
                        }), 503
                    
                    logger.info(f"[API Key] ✅ Ключ назначен пользователю: {masked_id}, статус: {status}")
                    
                    # После назначения ключа проверяем и активируем пробный период если нужно
                    trial_status_after = db.get_trial_status(telegram_id)
                    if trial_status_after.get('can_use', False) and not trial_status_after.get('is_active', False):
                        # Если пробный период еще не активирован, активируем его
                        trial_activated = db.activate_trial(telegram_id)
                        if trial_activated:
                            logger.info(f"[Trial] ✅ Пробный период активирован для пользователя: {masked_id}")
                except Exception as assign_error:
                    logger.error(f"[API Key] Ошибка при назначении ключа: {str(assign_error)}")
                    return jsonify({
                        "error": "Failed to assign API key",
                        "success": False
                    }), 500
            else:
                logger.info(f"[API Key] ✅ Ключ найден в БД для пользователя: {masked_id}")
            
            # Проверяем что ключ действительно получен
            if not api_key or len(api_key) == 0:
                logger.error(f"[API Key] ❌ API ключ пустой для пользователя: {masked_id}")
                return jsonify({
                    "error": "API key is empty",
                    "success": False
                }), 500
            
            # Маскируем API ключ в логах (показываем только последние 4 символа)
            masked_key = f"***{api_key[-4:]}" if api_key else "отсутствует"
            logger.info(f"[API Key] ✅ Возвращаем API ключ для пользователя: {masked_id} (ключ: {masked_key})")
            
            # Добавляем информацию о пробном периоде в ответ
            response_data = {
                "api_key": api_key,
                "success": True
            }
            
            # Добавляем статус пробного периода в ответ (опционально, для информации клиента)
            if is_trial_active:
                response_data["trial"] = {
                    "active": True,
                    "hours_remaining": hours_remaining
                }
            elif can_use_trial:
                response_data["trial"] = {
                    "active": False,
                    "can_activate": True
                }
            
            return jsonify(response_data), 200
            
        except Exception as e:
            logger.error(f"[API Key] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e), "success": False}), 500
    
    @app.route("/api/gemini/ws-proxy-info", methods=["GET", "OPTIONS"])
    def api_ws_proxy_info():
        """Возвращает информацию о WebSocket прокси для клиента"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            # Получаем API ключ из query параметров
            api_key = request.args.get('api_key')
            if not api_key:
                return jsonify({"error": "API key required"}), 400
            
            # Возвращаем URL для WebSocket прокси
            # Клиент будет подключаться к этому URL, а сервер проксирует к Google
            base_url = request.url_root.rstrip('/')
            ws_proxy_url = base_url.replace('http://', 'ws://').replace('https://', 'wss://') + '/api/gemini/ws-proxy'
            
            return jsonify({
                "ws_proxy_url": ws_proxy_url,
                "api_key_masked": api_key[:10] + "..." if len(api_key) > 10 else "***"
            }), 200
            
        except Exception as e:
            logger.error(f"[WS Proxy Info] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/gemini/live", methods=["POST", "OPTIONS"])
    def api_gemini_live():
        """API endpoint для Live общения с Gemini"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json
            telegram_id = data.get('telegram_id')
            audio_base64 = data.get('audio')  # base64 encoded audio
            
            if not telegram_id or not audio_base64:
                return jsonify({"error": "Missing telegram_id or audio"}), 400
            
            # Получаем API ключ пользователя
            api_key = key_manager.get_user_api_key(telegram_id)
            if not api_key:
                return jsonify({"error": "API key not found"}), 404
            
            # Получаем модель пользователя - используем Live модель
            model_key = db.get_user_model(telegram_id)
            # Проверяем, есть ли у модели поддержка голоса
            model_info = config.GEMINI_MODELS.get(model_key)
            
            # Если модель не поддерживает голос, используем Live модель
            if not model_info or not model_info.get('supports_voice'):
                model_info = config.GEMINI_MODELS.get('flash-live', config.GEMINI_MODELS['flash'])
            
            model_name = model_info.get('name', 'gemini-2.5-flash-live')
            
            # Декодируем аудио
            audio_data = base64.b64decode(audio_base64)
            
            # Используем asyncio для вызова async функции
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Создаем клиент Gemini
                client = new_genai.Client(api_key=api_key)
                
                # Определяем модель для Live
                model_name = model_info.get('name', 'gemini-2.5-flash-live')
                
                # Формируем содержимое с аудио
                audio_mime = "audio/webm"
                try:
                    audio_part = types.Part.from_bytes(data=audio_data, mime_type=audio_mime)
                except (AttributeError, TypeError):
                    # Fallback на inline_data
                    audio_base64_clean = base64.b64encode(audio_data).decode('utf-8')
                    audio_part = types.Part(
                        inline_data=types.Blob(data=audio_base64_clean, mime_type=audio_mime)
                    )
                
                contents = [
                    types.Content(
                        role="user",
                        parts=[audio_part],
                    ),
                ]
                
                # Конфигурация для генерации аудио ответа
                generate_content_config = types.GenerateContentConfig(
                    response_modalities=["AUDIO", "TEXT"],
                )
                
                # Синхронная функция для streaming
                def _generate_stream():
                    chunks = []
                    try:
                        for chunk in client.models.generate_content_stream(
                            model=model_name,
                            contents=contents,
                            config=generate_content_config,
                        ):
                            chunks.append(chunk)
                    except Exception as e:
                        logger.error(f"[API Live] Ошибка генерации: {e}")
                        raise
                    return chunks
                
                # Запускаем в executor
                chunks = loop.run_until_complete(asyncio.to_thread(_generate_stream))
                
                text_parts = []
                audio_response = None
                
                # Обрабатываем chunks
                for chunk in chunks:
                    if (
                        chunk.candidates is None
                        or chunk.candidates[0].content is None
                        or chunk.candidates[0].content.parts is None
                    ):
                        continue
                    
                    part = chunk.candidates[0].content.parts[0]
                    
                    # Проверяем аудио ответ
                    if part.inline_data and part.inline_data.data:
                        data_buffer = part.inline_data.data
                        if isinstance(data_buffer, str):
                            audio_response = base64.b64decode(data_buffer)
                        else:
                            audio_response = data_buffer
                    
                    # Проверяем текст
                    if hasattr(part, 'text') and part.text:
                        text_parts.append(part.text)
                
                response_text = '\n'.join(text_parts) if text_parts else "Ответ получен"
                audio_base64_response = base64.b64encode(audio_response).decode('utf-8') if audio_response else None
                
                return jsonify({
                    "text": response_text,
                    "audio": audio_base64_response
                }), 200
                
            except Exception as api_error:
                logger.error(f"[API Live] Ошибка API: {api_error}", exc_info=True)
                # Возвращаем простой текстовый ответ при ошибке
                return jsonify({
                    "text": "Произошла ошибка при обработке голосового сообщения. Попробуйте снова.",
                    "audio": None
                }), 200  # Возвращаем 200, чтобы не показывать ошибку пользователю
            finally:
                loop.close()
            
        except Exception as e:
            logger.error(f"[API Live] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/chat/save", methods=["POST", "OPTIONS"])
    def api_chat_save():
        """API endpoint для сохранения сообщений чата в БД"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json or {}
            telegram_id = data.get('telegram_id')
            chat_type = data.get('chat_type', 'generation')  # 'generation' или 'live'
            role = data.get('role')  # 'user' или 'model'
            content = data.get('content')
            context_type = data.get('context_type')  # 'generation_request', 'generation_response', 'live_message'
            
            if not telegram_id or not role or not content:
                return jsonify({"error": "Missing required fields"}), 400
            
            # Получаем активный чат пользователя или создаем новый
            from uuid import UUID
            chat = db.get_user_active_chat(telegram_id)
            
            chat_id = None
            if chat:
                # Проверяем, подходит ли чат по типу
                existing_chat_type = chat.get('chat_type')
                if existing_chat_type == chat_type:
                    chat_id = UUID(chat['chat_id'])
            
            if not chat_id:
                # Создаем новый чат нужного типа
                chat_title = "Генерация изображений" if chat_type == 'generation' else "Live общение"
                new_chat = db.create_chat(telegram_id, chat_title, chat_type)
                if new_chat:
                    chat_id = UUID(new_chat['chat_id'])
            
            # Сохраняем сообщение
            if chat_id:
                db.add_message(chat_id, role, content, context_type)
                return jsonify({
                    "success": True,
                    "chat_id": str(chat_id)
                }), 200
            else:
                return jsonify({
                    "error": "Failed to create or get chat",
                    "success": False
                }), 500
            
        except Exception as e:
            logger.error(f"[API Chat Save] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e), "success": False}), 500
    
    @app.route("/api/gemini/generate", methods=["POST", "OPTIONS"])
    def api_gemini_generate():
        """API endpoint для генерации изображений через Gemini"""
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json
            telegram_id = data.get('telegram_id')
            prompt = data.get('prompt', '')
            images_base64 = data.get('images', [])  # массив base64 изображений
            
            if not telegram_id:
                return jsonify({"error": "Missing telegram_id"}), 400
            
            if not prompt and not images_base64:
                return jsonify({"error": "Missing prompt and images"}), 400
            
            # Получаем API ключ пользователя
            api_key = key_manager.get_user_api_key(telegram_id)
            if not api_key:
                return jsonify({"error": "API key not found"}), 404
            
            # Получаем модель пользователя
            model_key = db.get_user_model(telegram_id)
            model_info = config.GEMINI_MODELS.get(model_key, config.GEMINI_MODELS['image-generation'])
            model_name = model_info.get('name', 'gemini-2.0-flash-image-generation')
            
            # Декодируем изображения если есть
            reference_images = []
            if images_base64:
                for img_b64 in images_base64[:2]:  # Максимум 2 изображения
                    img_data = base64.b64decode(img_b64)
                    reference_images.append(img_data)
            
            # Вызываем функцию генерации напрямую через asyncio
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                result = loop.run_until_complete(
                    generate_content_direct(
                        api_key,
                        prompt,
                        reference_images[0] if reference_images else None,
                        model_key if model_info.get('supports_image_generation') else 'image-generation'
                    )
                )
                
                text_response, generated_image = result
                
                # Кодируем изображение в base64 если есть
                image_base64 = None
                if generated_image:
                    image_base64 = base64.b64encode(generated_image).decode('utf-8')
                
                return jsonify({
                    "text": text_response or "Изображение сгенерировано",
                    "image": image_base64
                }), 200
                
            finally:
                loop.close()
            
        except Exception as e:
            logger.error(f"[API Generate] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    @app.route("/<path:path>")
    def serve_static(path):
        """Отдаем статические файлы из mini_app (style.css, app.js и т.д.)"""
        return send_from_directory(str(mini_app_dir), path)
    
    port = int(os.environ.get("PORT", 5000))
    
    # Отключаем логирование Flask (чтобы не засорять логи)
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    print(f"[flask] сервер запущен на порту {port}")
    print(f"[flask] Mini App доступен по адресу: http://0.0.0.0:{port}/")
    print(f"[flask] API endpoints:")
    print(f"  - /api/user/data - данные пользователя")
    print(f"  - /api/user/subscription - статус подписки")
    print(f"  - /api/gemini/api-key - получение API ключа")
    print(f"  - /api/gemini/live - Live общение")
    print(f"  - /api/gemini/generate - генерация изображений")
    print(f"  - /api/chat/save - сохранение сообщений чата")
    
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)

def run_cleanup_scheduler():
    """Запуск периодической очистки неактивных сессий"""
    import time
    
    logger.info("[Cleanup Scheduler] 🧹 Запущен планировщик очистки неактивных сессий (каждые 5 минут)")
    
    while True:
        try:
            # Ожидаем 5 минут перед первой проверкой
            time.sleep(5 * 60)
            
            # Запускаем очистку неактивных сессий (неактивны более 10 минут)
            freed_count = key_manager.cleanup_inactive_sessions(inactive_minutes=10)
            
            if freed_count > 0:
                logger.info(f"[Cleanup Scheduler] ✅ Очистка завершена: освобождено {freed_count} ключей")
            else:
                logger.debug("[Cleanup Scheduler] Нет неактивных сессий для очистки")
                
        except Exception as e:
            logger.error(f"[Cleanup Scheduler] Ошибка при очистке неактивных сессий: {e}", exc_info=True)
            # Ждем перед следующей попыткой
            time.sleep(60)

if __name__ == '__main__':
    # Flask запускается в отдельном daemon потоке (не блокирует)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Запускаем планировщик очистки неактивных сессий в отдельном потоке
    cleanup_thread = threading.Thread(target=run_cleanup_scheduler, daemon=True)
    cleanup_thread.start()
    logger.info("[Main] ✅ Запущены фоновые потоки: Flask сервер и планировщик очистки")
    
    # Небольшая задержка для запуска Flask сервера
    import time
    time.sleep(2)
    
    # Бот запускается в главном потоке (run_polling сам управляет event loop)
    start_bot()

