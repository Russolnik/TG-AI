"""
Основной файл Telegram-бота
"""
import logging
import asyncio
import threading
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
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
from typing import Optional
from google import genai as new_genai
from google.genai import types

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
    
    # Получаем данные пользователя из Telegram
    username = user.username if hasattr(user, 'username') and user.username else None
    first_name = user.first_name if hasattr(user, 'first_name') and user.first_name else None
    # Получаем фото профиля (если доступно)
    photo_url = None
    try:
        # Получаем фото профиля пользователя через get_user_profile_photos
        profile_photos = await context.bot.get_user_profile_photos(telegram_id, limit=1)
        if profile_photos and profile_photos.photos:
            # Берем самое большое фото
            photo = profile_photos.photos[0][-1]  # Последний элемент - самое большое фото
            photo_file = await context.bot.get_file(photo.file_id)
            # Формируем URL для доступа к фото
            photo_url = f"https://api.telegram.org/file/bot{context.bot.token}/{photo_file.file_path}"
    except Exception as e:
        logger.warning(f"Не удалось получить фото пользователя {telegram_id}: {e}")
    
    try:
        # Получаем или назначаем ключ пользователю (с данными профиля)
        key_id, api_key, status = key_manager.assign_key_to_user(telegram_id, 
                                                                 username=username, 
                                                                 first_name=first_name, 
                                                                 photo_url=photo_url)
        
        if status == "limit_exceeded":
            await update.message.reply_text(
                "⚠️ Извините, лимит пользователей временно исчерпан. "
                "Пожалуйста, попробуйте позже."
            )
            return
        elif status == "existing_user":
            welcome_msg = (
                "👋 Добро пожаловать обратно!\n\n"
                "Я твой помощник на основе Gemini.\n\n"
                "Что я умею:\n"
                "• 💬 Текстовый чат\n"
                "• 🎙️ Обработка голосовых сообщений\n"
                "• 📷 Анализ фотографий\n"
                "• 📄 Обработка файлов (PDF, TXT, аудио) до 200 МБ\n\n"
                "💡 **Не забудьте обновить параметры о себе!**\n"
                "Используйте кнопку ⚙️ Параметры, чтобы рассказать о себе, своих интересах "
                "или желаемом стиле общения.\n\n"
                "Отправьте мне сообщение или используйте меню для начала!"
            )
        else:
            welcome_msg = (
                "👋 Добро пожаловать!\n\n"
                "Я твой помощник на основе Gemini.\n\n"
                "Что я умею:\n"
                "• 💬 Текстовый чат\n"
                "• 🎙️ Обработка голосовых сообщений\n"
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
        
        # Создаем клавиатуру для выбора модели
        keyboard = []
        for model_key, model_info in config.GEMINI_MODELS.items():
            if model_info['available']:
                # Добавляем отметку о текущей выбранной модели
                prefix = "✅ " if model_key == current_model else ""
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
            f"Выберите модель из списка ниже:"
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
            await query.edit_message_text(
                "🔒 Эта модель недоступна. Требуется подписка на Google AI Pro.\n\n"
                "Используйте бесплатные модели: Gemini 2.5 Flash."
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
            if not model_info.get('is_free', True) and not db.has_active_subscription(telegram_id, username):
                await query.edit_message_text(
                    "💎 **Требуется подписка**\n\n"
                    "Эта модель доступна только для пользователей с активной подпиской.\n\n"
                    "Вы можете приобрести подписку через кнопку меню или команду /subscription.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # Если модель открывает mini app, открываем его вместо смены модели
            if model_info.get('opens_mini_app', False):
                mini_app_mode = model_info.get('mini_app_mode', 'generation')
                mini_app_url = config.MINI_APP_URL
                
                # Убираем завершающий слэш если есть
                mini_app_url = mini_app_url.rstrip('/')
                
                # Добавляем параметр режима к URL
                mini_app_url_with_mode = f"{mini_app_url}?mode={mini_app_mode}"
                
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

async def setup_main_menu(message):
    """Настройка постоянного меню с кнопками"""
    mini_app_url = get_mini_app_url()
    main_url = f"{mini_app_url}/main.html"
    
    keyboard = [
        [KeyboardButton("📱 Открыть приложение", web_app={"url": main_url})],
        [KeyboardButton("🤖 Модель"), KeyboardButton("⚙️ Параметры")],
        [KeyboardButton("💎 Подписка"), KeyboardButton("➕ Новый чат")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await message.reply_text(
        "💡 Используйте кнопки меню для навигации:",
        reply_markup=reply_markup
    )

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
    elif text == "➕ Новый чат":
        await new_chat_command(update, context)
    elif text == "📱 Открыть приложение":
        # Кнопка WebApp обрабатывается автоматически Telegram
        # Можно добавить логику здесь если нужно
        pass

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

async def subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /subscription - информация о подписке"""
    telegram_id = update.effective_user.id
    
    try:
        # Получаем текущую подписку
        subscription = db.get_active_subscription(telegram_id)
        
        if subscription:
            # Если есть активная подписка, показываем информацию
            from datetime import datetime, timezone
            end_date = datetime.fromisoformat(subscription['end_date'].replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            days_left = (end_date - now).days
            
            message_text = (
                f"💎 **Ваша подписка**\n\n"
                f"• Тип: {subscription['subscription_type'].replace('_', ' ').title()}\n"
                f"• Действует до: {end_date.strftime('%d.%m.%Y %H:%M')}\n"
                f"• Осталось дней: {days_left}\n\n"
                f"✅ У вас есть доступ ко всем платным моделям."
            )
        else:
            # Если нет подписки, показываем информацию о том, как приобрести
            message_text = (
                "💎 **Подписка**\n\n"
                "Для доступа к платным моделям требуется подписка.\n\n"
                "В данный момент система подписок находится в разработке.\n"
                "Пожалуйста, обратитесь к администратору для получения доступа."
            )
        
        await update.message.reply_text(
            message_text,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Ошибка в команде /subscription: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при получении информации о подписке. Попробуйте позже."
        )

async def subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback для управления подпиской (отключено до реализации)"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "💎 **Подписка**\n\n"
        "Система подписок находится в разработке.\n"
        "Пожалуйста, обратитесь к администратору для получения доступа.",
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
        about_url = f"{mini_app_url}/about.html"
        
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
        main_url = f"{mini_app_url}/main.html"
        
        logger.info(f"Открытие главной страницы Mini App: {main_url}")
        
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
                    
                    # Если не было изображения, но был запрос на генерацию
                    await update.message.reply_text(
                        "⚠️ Изображение не было сгенерировано.\n\n"
                        "При генерации произошла ошибка - модель вернула только текстовый ответ.\n\n"
                        "Попробуйте еще раз или переформулируйте запрос."
                    )
                else:
                    # Не удалось получить ни изображение, ни текст
                    await status_msg.edit_text(
                        "❌ **Не удалось сгенерировать изображение.**\n\n"
                        "При генерации произошла ошибка - изображение не было создано.\n\n"
                        "**Возможные причины:**\n"
                        "• Сервис временно перегружен\n"
                        "• Модель временно недоступна\n\n"
                        "Пожалуйста, попробуйте еще раз через несколько минут."
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
                    
                    # Если не было изображения, но был запрос на генерацию
                    await update.message.reply_text(
                        "⚠️ Изображение не было сгенерировано.\n\n"
                        "Модель вернула только текстовый ответ. Попробуйте еще раз."
                    )
                else:
                    # Не удалось получить ни изображение, ни текст
                    await status_msg.edit_text(
                        "❌ **Не удалось сгенерировать изображение.**\n\n"
                        "При генерации произошла ошибка - изображение не было создано.\n\n"
                        "**Возможные причины:**\n"
                        "• Сервис временно перегружен\n"
                        "• Модель временно недоступна\n\n"
                        "Пожалуйста, попробуйте еще раз через несколько минут."
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
    logger.error(f"Ошибка при обработке обновления: {context.error}", exc_info=context.error)
    
    if update and update.message:
        try:
            await update.message.reply_text(
                "❌ Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже."
            )
        except:
            pass

def start_bot():
    """Синхронная функция запуска бота"""
    # Создаем приложение
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("model", model_command))
    application.add_handler(CommandHandler("params", params_command))
    application.add_handler(CommandHandler("subscription", subscription_command))
    application.add_handler(CommandHandler("about", about_project_command))
    application.add_handler(CommandHandler("app", open_app_command))
    
    # Регистрируем обработчики callback
    application.add_handler(CallbackQueryHandler(model_callback, pattern="^model_"))
    application.add_handler(CallbackQueryHandler(params_callback, pattern="^param_"))
    application.add_handler(CallbackQueryHandler(subscription_callback, pattern="^sub_"))
    
    # Регистрируем обработчики сообщений
    # Сначала обрабатываем кнопки меню (до текстовых сообщений)
    application.add_handler(MessageHandler(filters.Regex("^(🤖 Модель|⚙️ Параметры|💎 Подписка|➕ Новый чат)$"), handle_menu_button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Глобальный обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Устанавливаем команды бота через post_init (вызывается после инициализации)
    async def post_init(app: Application):
        """Установка команд бота после инициализации"""
        try:
            # Ждем, пока бот полностью инициализирован
            await asyncio.sleep(0.1)
            await app.bot.set_my_commands([
            BotCommand("start", "Запустить бота и зарегистрироваться"),
            BotCommand("model", "Выбрать модель AI (Flash/Pro)"),
            BotCommand("params", "Настроить параметры (кастомизация)")
        ])
            logger.info("Команды бота установлены")
        except Exception as e:
            logger.warning(f"Не удалось установить команды бота: {e}")
    
    application.post_init = post_init
    
    # Запускаем бота (run_polling сам управляет event loop и инициализацией)
    logger.info("Запуск бота...")
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            close_loop=False,
            drop_pending_updates=True
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
    
    @app.route("/api/user/subscription", methods=["POST", "OPTIONS"])
    def api_user_subscription():
        """API endpoint для получения статуса подписки пользователя"""
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
        """
        if request.method == 'OPTIONS':
            return '', 200
        
        try:
            data = request.json or {}
            telegram_id = data.get('telegram_id')
            
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
            
            # Получаем API ключ пользователя
            api_key = key_manager.get_user_api_key(telegram_id)
            has_key = api_key is not None
            key_length = len(api_key) if api_key else 0
            logger.info(f"[API Key] Ключ в БД: {'найден' if has_key else 'не найден'}, длина: {key_length}")
            
            # Если ключа нет, назначаем новый (с проверкой лимита через get_available_key)
            if not api_key:
                logger.info(f"[API Key] Назначаем новый ключ для пользователя: {masked_id}")
                try:
                    key_id, api_key, status = key_manager.assign_key_to_user(telegram_id)
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
            return jsonify({
                "api_key": api_key,
                "success": True
            }), 200
            
        except Exception as e:
            logger.error(f"[API Key] Ошибка: {e}", exc_info=True)
            return jsonify({"error": str(e), "success": False}), 500
    
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

if __name__ == '__main__':
    # Flask запускается в отдельном daemon потоке (не блокирует)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Небольшая задержка для запуска Flask сервера
    import time
    time.sleep(2)
    
    # Бот запускается в главном потоке (run_polling сам управляет event loop)
    start_bot()

