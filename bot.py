"""
Основной файл Telegram-бота
"""
import logging
import asyncio
from flask import Flask
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode
import re
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
        logger.error(f"Ошибка в команде /start для пользователя {telegram_id}: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Произошла ошибка при регистрации.\n\n"
            f"Детали: {str(e)}\n\n"
            f"Пожалуйста, попробуйте позже или обратитесь к администратору."
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
    keyboard = [
        [KeyboardButton("🤖 Модель"), KeyboardButton("⚙️ Параметры")],
        [KeyboardButton("➕ Новый чат")],
        [KeyboardButton("ℹ️ О проекте")]
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
    elif text == "➕ Новый чат":
        await new_chat_command(update, context)
    elif text == "ℹ️ О проекте":
        await about_project_command(update, context)

async def new_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание нового чата"""
    telegram_id = update.effective_user.id
    
    try:
        # Получаем список всех чатов пользователя для нумерации
        user_chats = db.get_user_chats(telegram_id)
        chat_number = len(user_chats) + 1
        
        # Создаем новый чат
        new_chat = db.create_chat(telegram_id, f"Чат {chat_number}")
        
        if new_chat:
            await update.message.reply_text(
                f"✅ **Новый чат создан!**\n\n"
                f"Вы можете начать новый диалог с чистого листа.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("❌ Не удалось создать новый чат.")
    except Exception as e:
        logger.error(f"Ошибка при создании нового чата: {e}")
        await update.message.reply_text("❌ Произошла ошибка при создании чата.")

async def about_project_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды "О проекте" - открывает Mini App"""
    try:
        mini_app_url = config.MINI_APP_URL
        if not mini_app_url or mini_app_url == "https://your-app.netlify.app":
            await update.message.reply_text(
                "ℹ️ **О проекте**\n\n"
                "AI Assistant — Telegram-бот с интеграцией Google Gemini API.\n\n"
                "Что я умею:\n"
                "• 💬 Текстовый чат\n"
                "• 🎙️ Обработка голосовых сообщений\n"
                "• 📷 Анализ фотографий\n"
                "• 📄 Обработка файлов (PDF, TXT, аудио)\n\n"
                "📞 Связь: @rusolnik\n\n"
                "💎 Поддержать проект: @rusolnik",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        keyboard = [
            [InlineKeyboardButton("ℹ️ О проекте", web_app={"url": mini_app_url})]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "ℹ️ **Откройте страницу \"О проекте\"**\n\n"
            "Нажмите на кнопку ниже, чтобы узнать больше о проекте, "
            "его возможностях и связаться с создателем.",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка в команде 'О проекте': {e}")
        await update.message.reply_text("❌ Произошла ошибка при открытии страницы.")

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
        logger.info(f"Фоновый запрос для пользователя {telegram_id} выполнен успешно")
    except Exception as e:
        logger.error(f"Ошибка фонового запроса для пользователя {telegram_id}: {e}")
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

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    telegram_id = update.effective_user.id
    user_text = update.message.text
    
    try:
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
        
        # Сохраняем сообщение пользователя
        db.add_message(chat_id, "user", user_text)
        
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
        
        # Получаем обработчики с правильным API-ключом
        user_handlers = get_handlers_for_user(telegram_id)
        
        # Получаем ответ от Gemini
        response = user_handlers.gemini.chat(chat_history, context_window=config.CONTEXT_WINDOW_SIZE)
        
        # Сохраняем ответ модели
        db.add_message(chat_id, "model", response)
        
        # Удаляем статус и отправляем ответ с форматированием
        await status_msg.delete()
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
        
        # Отправляем статус обработки
        status_msg = await update.message.reply_text("💬 Запрос обрабатывается...")
        
        # Скачиваем фото
        photo_file = await context.bot.get_file(photo.file_id)
        photo_data = await photo_file.download_as_bytearray()
        
        # Получаем подпись если есть
        caption = update.message.caption
        
        # Получаем обработчики
        user_handlers = get_handlers_for_user(telegram_id)
        
        # Обрабатываем фото
        response = await user_handlers.handle_photo(bytes(photo_data), caption)
        
        # НЕ сохраняем медиа в историю - обрабатываем независимо
        # Это гарантирует, что следующее текстовое сообщение не будет пытаться обработать это фото снова
        
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

def main():
    """Главная функция запуска бота"""
    # Создаем приложение
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("model", model_command))
    application.add_handler(CommandHandler("params", params_command))
    
    # Регистрируем обработчики callback
    application.add_handler(CallbackQueryHandler(model_callback, pattern="^model_"))
    application.add_handler(CallbackQueryHandler(params_callback, pattern="^param_"))
    
    # Регистрируем обработчики сообщений
    # Сначала обрабатываем кнопки меню (до текстовых сообщений)
    application.add_handler(MessageHandler(filters.Regex("^(🤖 Модель|⚙️ Параметры|➕ Новый чат|ℹ️ О проекте)$"), handle_menu_button))
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
            BotCommand("model", "Выбрать модель AI (Flash/Pro)"),
            BotCommand("params", "Настроить параметры (кастомизация)")
        ])
    
    application.post_init = post_init
    
    # Запускаем бота
    logger.info("Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()


def run_flask() -> None:
    """Run lightweight Flask app required by hosting."""
    print("[flask] starting auxiliary web server...")
    app = Flask(__name__)

    @app.route("/")
    def home() -> tuple[str, int]:
        return "Telegram Bot is running (long polling in a separate thread).", 200

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    bot_thread = threading.Thread(target=lambda: asyncio.run(start_bot()), daemon=True)
    bot_thread.start()
    run_flask()
