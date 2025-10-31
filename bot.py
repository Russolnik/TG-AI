"""
Основной файл Telegram-бота
"""
import logging
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode
import config
from database import Database
from api_key_manager import APIKeyManager
from gemini_client import GeminiClient
from handlers import ContentHandlers
from uuid import UUID

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    telegram_id = update.effective_user.id
    
    try:
        key_id, api_key, status = key_manager.assign_key_to_user(telegram_id)
        
        if status == "limit_exceeded":
            await update.message.reply_text(
                "⚠️ Извините, лимит пользователей временно исчерпан. "
                "Пожалуйста, попробуйте позже."
            )
            return
        elif status == "existing_user":
            welcome_msg = (
                "👋 Добро пожаловать обратно!\n\n"
                "Я ваш AI-ассистент на основе Gemini.\n\n"
                "Что я умею:\n"
                "• 💬 Текстовый чат\n"
                "• 🎙️ Обработка голосовых сообщений\n"
                "• 📷 Анализ фотографий\n"
                "• 📄 Обработка файлов (PDF, TXT, аудио)\n\n"
                "Отправьте мне сообщение или используйте меню для начала!"
            )
        else:
            welcome_msg = (
                "👋 Добро пожаловать!\n\n"
                "Я ваш AI-ассистент на основе Gemini.\n\n"
                "Что я умею:\n"
                "• 💬 Текстовый чат\n"
                "• 🎙️ Обработка голосовых сообщений\n"
                "• 📷 Анализ фотографий\n"
                "• 📄 Обработка файлов (PDF, TXT, аудио)\n\n"
                "Отправьте мне сообщение или используйте меню для начала!"
            )
        
        await update.message.reply_text(welcome_msg)
        
        # Создаем меню с кнопкой Mini App
        keyboard = [
            [InlineKeyboardButton("📱 Мои Диалоги", web_app={"url": config.MINI_APP_URL})]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "💡 Откройте 'Мои Диалоги' для управления чатами:",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при регистрации. Пожалуйста, попробуйте позже."
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
        
        message_text = (
            f"🤖 **Выбор модели AI**\n\n"
            f"Текущая модель: **{current_model_info['display_name']}**\n\n"
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
                "Используйте бесплатные модели: Gemini 2.5 Flash или Gemini 1.5 Flash."
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

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    telegram_id = update.effective_user.id
    user_text = update.message.text
    
    try:
        # Получаем активный чат пользователя
        chat = db.get_user_active_chat(telegram_id)
        if not chat:
            # Создаем новый чат если его нет
            chat = db.create_chat(telegram_id, "Чат 1")
            if not chat:
                await update.message.reply_text("❌ Ошибка при создании чата.")
                return
        
        chat_id = UUID(chat['chat_id'])
        
        # Сохраняем сообщение пользователя
        db.add_message(chat_id, "user", user_text)
        
        # Получаем историю сообщений для контекста
        messages = db.get_chat_messages(chat_id, limit=config.CONTEXT_WINDOW_SIZE)
        
        # Формируем историю для Gemini (только role и content)
        chat_history = [
            {"role": msg['role'], "content": msg['content']}
            for msg in messages
        ]
        
        # Отправляем статус обработки
        status_msg = await update.message.reply_text("💬 Обрабатываю запрос...")
        
        # Получаем обработчики с правильным API-ключом
        user_handlers = get_handlers_for_user(telegram_id)
        
        # Получаем ответ от Gemini
        response = user_handlers.gemini.chat(chat_history, context_window=config.CONTEXT_WINDOW_SIZE)
        
        # Сохраняем ответ модели
        db.add_message(chat_id, "model", response)
        
        # Удаляем статус и отправляем ответ
        await status_msg.delete()
        await update.message.reply_text(response)
        
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
        chat = db.get_user_active_chat(telegram_id)
        if not chat:
            chat = db.create_chat(telegram_id, "Чат 1")
        chat_id = UUID(chat['chat_id'])
        
        # Отправляем индикатор
        status_msg = await update.message.reply_text("🎙️ Транскрибирую голосовое сообщение...")
        
        # Скачиваем файл
        voice_file = await context.bot.get_file(voice.file_id)
        voice_path = f"temp_{voice.file_id}.ogg"
        await voice_file.download_to_drive(voice_path)
        
        try:
            # Получаем подпись если есть
            caption = update.message.caption
            
            # Получаем обработчики
            user_handlers = get_handlers_for_user(telegram_id)
            
            # Обрабатываем голос
            response = await user_handlers.handle_voice(voice_path, caption)
            
            # Сохраняем в БД
            db.add_message(chat_id, "user", f"[Голосовое сообщение]{f': {caption}' if caption else ''}")
            db.add_message(chat_id, "model", response)
            
            await status_msg.delete()
            await update.message.reply_text(response)
        finally:
            # Удаляем временный файл
            import os
            if os.path.exists(voice_path):
                os.unlink(voice_path)
                
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
        chat = db.get_user_active_chat(telegram_id)
        if not chat:
            chat = db.create_chat(telegram_id, "Чат 1")
        chat_id = UUID(chat['chat_id'])
        
        # Отправляем индикатор
        status_msg = await update.message.reply_text("📷 Анализирую фото...")
        
        # Скачиваем фото
        photo_file = await context.bot.get_file(photo.file_id)
        photo_data = await photo_file.download_as_bytearray()
        
        # Получаем подпись если есть
        caption = update.message.caption
        
        # Получаем обработчики
        user_handlers = get_handlers_for_user(telegram_id)
        
        # Обрабатываем фото
        response = await user_handlers.handle_photo(bytes(photo_data), caption)
        
        # Сохраняем в БД
        db.add_message(chat_id, "user", f"[Фото]{f': {caption}' if caption else ''}")
        db.add_message(chat_id, "model", response)
        
        await status_msg.delete()
        await update.message.reply_text(response)
        
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
        chat = db.get_user_active_chat(telegram_id)
        if not chat:
            chat = db.create_chat(telegram_id, "Чат 1")
        chat_id = UUID(chat['chat_id'])
        
        # Отправляем индикатор
        status_msg = await update.message.reply_text("📝 Обрабатываю файл...")
        
        # Скачиваем файл
        doc_file = await context.bot.get_file(document.file_id)
        file_path = f"temp_{document.file_id}_{document.file_name}"
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
                db.add_message(chat_id, "user", f"[PDF: {document.file_name}]{f' - {caption}' if caption else ''}")
            elif file_name.endswith(('.txt', '.text')):
                response = await user_handlers.handle_text_file(file_path, caption)
                db.add_message(chat_id, "user", f"[Текстовый файл: {document.file_name}]{f' - {caption}' if caption else ''}")
            elif file_name.endswith(('.mp3', '.wav', '.ogg', '.m4a', '.flac')):
                response = await user_handlers.handle_audio_file(file_path, caption)
                db.add_message(chat_id, "user", f"[Аудио файл: {document.file_name}]{f' - {caption}' if caption else ''}")
            else:
                response = "❌ Неподдерживаемый тип файла. Поддерживаются: PDF, TXT, аудио (MP3, WAV, OGG)."
            
            if response:
                db.add_message(chat_id, "model", response)
                await status_msg.delete()
                await update.message.reply_text(response)
                
        finally:
            # Удаляем временный файл
            import os
            if os.path.exists(file_path):
                os.unlink(file_path)
                
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

def main():
    """Главная функция запуска бота"""
    # Создаем приложение
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("model", model_command))
    
    # Регистрируем обработчики callback
    application.add_handler(CallbackQueryHandler(model_callback, pattern="^model_"))
    
    # Регистрируем обработчики сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Глобальный обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Устанавливаем команды бота
    async def post_init(application: Application):
        await application.bot.set_my_commands([
            BotCommand("start", "Запустить бота и зарегистрироваться"),
            BotCommand("model", "Выбрать модель AI (Flash/Pro)")
        ])
    
    application.post_init = post_init
    
    # Запускаем бота
    logger.info("Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

