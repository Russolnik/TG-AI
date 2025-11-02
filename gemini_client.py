"""
Клиент для работы с Google Gemini API
"""
import google.generativeai as genai
from typing import List, Dict, Optional
import base64
from io import BytesIO
from PIL import Image
import config
import os

# Настройка транспорта для Gemini API
# Все запросы идут с сервера, используя IP сервера автоматически

class GeminiClient:
    def __init__(self, api_key: str, model_name: str = 'flash'):
        """
        Инициализация клиента Gemini
        
        Args:
            api_key: API ключ Gemini
            model_name: Имя модели из config.GEMINI_MODELS (flash, pro, flash-latest)
        """
        # Настройка - запросы всегда идут с сервера, используя IP сервера
        genai.configure(api_key=api_key)
        self.api_key = api_key  # Сохраняем для использования в новой библиотеке
        
        # Получаем конфигурацию модели
        model_config = config.GEMINI_MODELS.get(
            model_name, 
            config.GEMINI_MODELS[config.DEFAULT_MODEL]
        )
        
        self.model_name = model_config['name']
        self.vision_model_name = model_config.get('vision_name', model_config['name'])
        
        # Инициализируем модели
        try:
            self.model = genai.GenerativeModel(self.model_name)
            self.vision_model = genai.GenerativeModel(self.vision_model_name)
        except Exception as e:
            print(f"Ошибка инициализации модели {self.model_name}: {e}")
            # Fallback на модель по умолчанию
            default_config = config.GEMINI_MODELS[config.DEFAULT_MODEL]
            self.model_name = default_config['name']
            self.vision_model_name = default_config.get('vision_name', default_config['name'])
            self.model = genai.GenerativeModel(self.model_name)
            self.vision_model = genai.GenerativeModel(self.vision_model_name)
    
    def chat(self, messages: List[Dict], context_window: Optional[int] = None) -> str:
        """
        Отправить запрос в Gemini для текстового чата
        
        Args:
            messages: Список сообщений в формате [{"role": "user|model", "content": "текст"}, ...]
            context_window: Ограничение количества последних сообщений (для экономии токенов)
        
        Returns:
            Ответ от модели
        """
        try:
            # Если задан контекст, берем только последние N сообщений
            if context_window and len(messages) > context_window:
                messages = messages[-context_window:]
            
            # Добавляем инструкцию для форматирования ответа (только для первого пользовательского сообщения)
            system_prompt = (
                "Ты AI-ассистент, общайся с пользователем от первого лица (я, мне, меня, мой, я могу, я знаю и т.д.). "
                "Отвечай так, как будто разговариваешь с пользователем напрямую. "
                "Используй Markdown форматирование: **жирный текст** для важных моментов, "
                "*курсив* для акцентов, эмодзи где уместно, "
                "и структурируй ответ для лучшей читаемости."
            )
            
            # Преобразуем историю в формат для Gemini
            # Gemini использует чередующиеся сообщения user/model
            chat_history = []
            for i, msg in enumerate(messages):
                role = "user" if msg['role'] == 'user' else "model"
                content = msg['content']
                
                # Добавляем системный промпт к первому пользовательскому сообщению
                if role == "user" and i == 0:
                    content = f"{system_prompt}\n\n{content}"
                
                chat_history.append({
                    'role': role,
                    'parts': [{'text': content}]
                })
            
            # Если есть история, используем chat
            if len(chat_history) > 1:
                # Создаем новую сессию чата или продолжаем существующую
                chat = self.model.start_chat(history=chat_history[:-1] if len(chat_history) > 1 else [])
                last_message = chat_history[-1]['parts'][0]['text']
                response = chat.send_message(last_message)
            else:
                # Первое сообщение
                response = self.model.generate_content(messages[0]['content'])
            
            return response.text if response.text else "Извините, не удалось получить ответ от модели."
        except Exception as e:
            print(f"Ошибка при обращении к Gemini API: {e}")
            return f"Произошла ошибка при обработке запроса: {str(e)}"
    
    def analyze_image(self, image_data: bytes, user_question: str = "Что на этом изображении?", chat_history: Optional[List[Dict]] = None) -> str:
        """
        Анализ изображения с помощью Gemini Vision
        
        Args:
            image_data: Байты изображения
            user_question: Вопрос пользователя к изображению
            chat_history: История чата для контекста (опционально)
        
        Returns:
            Ответ модели
        """
        try:
            # Конвертируем байты в PIL Image
            image = Image.open(BytesIO(image_data))
            
            # Если есть история чата, формируем промпт с контекстом
            if chat_history and len(chat_history) > 0:
                # Добавляем контекст предыдущего диалога
                history_text = "\n".join([
                    f"{'Пользователь' if msg['role'] == 'user' else 'Ассистент'}: {msg['content'][:200]}"
                    for msg in chat_history[-5:]  # Последние 5 сообщений для контекста
                ])
                
                # Объединяем историю и вопрос пользователя
                enhanced_question = f"{user_question}\n\nКонтекст предыдущего диалога:\n{history_text}\n\nЕсли вопрос относится к тому, что обсуждалось ранее, используй эту информацию для ответа."
                
                # Отправляем запрос в vision модель с контекстом
                response = self.vision_model.generate_content([
                    enhanced_question,
                    image
                ])
            else:
                # Обычный запрос без истории
                response = self.vision_model.generate_content([
                    user_question,
                    image
                ])
            
            return response.text if response.text else "Не удалось проанализировать изображение."
        except Exception as e:
            print(f"Ошибка при анализе изображения: {e}")
            return f"Произошла ошибка при анализе изображения: {str(e)}"
    
    def process_text_from_file(self, text_content: str, user_question: Optional[str] = None) -> str:
        """
        Обработать текст из файла
        
        Args:
            text_content: Текст из файла
            user_question: Вопрос пользователя (если есть)
        
        Returns:
            Ответ модели
        """
        try:
            if user_question:
                prompt = f"Пользователь предоставил следующий текст:\n\n{text_content}\n\nВопрос пользователя: {user_question}\n\nОтветьте на вопрос пользователя, используя предоставленный текст."
            else:
                prompt = f"Проанализируйте и кратко перескажите следующий текст:\n\n{text_content}"
            
            response = self.model.generate_content(prompt)
            return response.text if response.text else "Не удалось обработать текст из файла."
        except Exception as e:
            print(f"Ошибка при обработке текста из файла: {e}")
            return f"Произошла ошибка при обработке файла: {str(e)}"
    
    def analyze_audio(self, audio_data: bytes, mime_type: str, user_question: Optional[str] = None, chat_history: Optional[List[Dict]] = None) -> str:
        """
        Обработка аудио через Gemini API
        
        Args:
            audio_data: Байты аудио файла
            mime_type: MIME тип аудио (audio/ogg, audio/mpeg, и т.д.)
            user_question: Вопрос пользователя (если есть)
        
        Returns:
            Ответ от модели с транскрипцией и обработкой
        """
        try:
            import base64
            
            # Конвертируем аудио в base64
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            
            # Формируем промпт - ответ от первого лица с поиском в истории чата
            history_context = ""
            if chat_history and len(chat_history) > 0:
                # Добавляем контекст истории для поиска информации
                history_text = "\n".join([
                    f"{'Пользователь' if msg['role'] == 'user' else 'Ассистент'}: {msg['content'][:200]}"
                    for msg in chat_history[-5:]  # Последние 5 сообщений для контекста
                ])
                history_context = f"\n\nКонтекст предыдущего диалога:\n{history_text}\n\nЕсли вопрос относится к тому, что обсуждалось ранее, используй эту информацию для ответа."
            
            if user_question:
                prompt_text = (
                    "Транскрибируй голосовое сообщение. "
                    "Перед ответом обязательно проверь историю диалога выше - возможно, ответ уже был дан ранее или информация есть в контексте. "
                    "Ответь на вопрос КОНКРЕТНО и ЧЕТКО, обращаясь к пользователю от первого лица (я, мне, меня). "
                    "Если в истории чата есть информация, которая отвечает на вопрос, используй её. "
                    "Если не можешь распознать или понять вопрос, скажи: 'Извини, я не смог разобрать твой вопрос' или 'К сожалению, я не распознал все слова в твоем сообщении'. "
                    "Если понял вопрос, ответь напрямую. "
                    "Не пиши 'Транскрипция:' или 'Ответ:', просто сразу отвечай. "
                    "Используй Markdown форматирование: **жирный текст** для важного, эмодзи где уместно."
                )
            else:
                prompt_text = (
                    "Транскрибируй голосовое сообщение. "
                    "Перед ответом обязательно проверь историю диалога выше - возможно, ответ уже был дан ранее или информация есть в контексте. "
                    "Ответь на вопрос или запрос КОНКРЕТНО и ЧЕТКО, обращаясь к пользователю от первого лица (я, мне, меня, мой). "
                    "Если в истории чата есть информация, которая отвечает на вопрос (например, пользователь ранее рассказывал о своих интересах, предпочтениях, фактах), обязательно используй эту информацию. "
                    "Если не можешь распознать или понять вопрос, скажи: 'Извини, я не смог ответить на твой вопрос, я не разобрал его' или 'К сожалению, я не смог распознать все слова в твоем голосовом сообщении'. "
                    "Если понял вопрос, ответь напрямую от первого лица, используя информацию из истории если она есть. "
                    "Не пиши 'Транскрипция:' или 'Ответ на содержание:', просто сразу отвечай от своего имени. "
                    "Используй Markdown форматирование: **жирный текст** для важного, эмодзи где уместно для читаемости."
                ) + history_context
            
            # Создаем части контента для Gemini API
            # Используем правильный формат для мультимодального контента
            import google.generativeai as genai
            
            # Формируем части: текст и аудио
            parts = [
                {"text": prompt_text},
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": audio_base64
                    }
                }
            ]
            
            # Если есть история, сначала отправляем её в chat, затем аудио
            if chat_history and len(chat_history) > 0:
                # Создаем сессию чата с историей
                chat_history_formatted = []
                for msg in chat_history:
                    role = "user" if msg['role'] == 'user' else "model"
                    chat_history_formatted.append({
                        'role': role,
                        'parts': [{'text': msg['content']}]
                    })
                
                # Создаем chat с историей
                chat = self.model.start_chat(history=chat_history_formatted[:-1] if len(chat_history_formatted) > 1 else [])
                # Отправляем промпт с аудио
                response = chat.send_message(parts)
            else:
                # Отправляем в Gemini без истории
                response = self.model.generate_content(parts)
            
            return response.text if response.text else "Не удалось обработать голосовое сообщение."
        except Exception as e:
            print(f"Ошибка при обработке аудио: {e}")
            return f"Произошла ошибка при обработке аудио: {str(e)}"
    
    async def generate_image(self, prompt: str, reference_image: Optional[bytes] = None) -> Optional[bytes]:
        """
        Генерация изображения через gemini-2.5-flash-image напрямую (без посредничества)
        
        Args:
            prompt: Текстовое описание изображения
            reference_image: Опциональное референсное изображение (байты)
        
        Returns:
            Байты сгенерированного изображения или None при ошибке
        """
        try:
            from google import genai as new_genai
            from google.genai import types
            import base64
            
            # Используем сохраненный API ключ из конструктора
            api_key = self.api_key
            
            if not api_key:
                print("[Генерация изображений] API ключ не найден")
                return None
            
            # Создаем клиент с новой библиотекой
            client = new_genai.Client(api_key=api_key)
            
            # Определяем модель для генерации изображений
            # Используем специальную модель для генерации изображений из конфига
            model = None
            if 'image-generation' in config.GEMINI_MODELS:
                model = config.GEMINI_MODELS['image-generation']['name']
            else:
                # Fallback на хардкод, если модель не найдена в конфиге
                model = "gemini-2.0-flash-image-generation"
            
            print(f"[Генерация изображений] Используется модель: {model}")
            print(f"[Генерация изображений] Промпт: {prompt}")
            
            # Формируем содержимое запроса
            # Если есть референсное изображение, добавляем его
            if reference_image:
                # Определяем MIME тип изображения
                image_mime = "image/png"  # По умолчанию
                # Пробуем определить по первым байтам
                if reference_image.startswith(b'\xff\xd8'):
                    image_mime = "image/jpeg"
                elif reference_image.startswith(b'\x89PNG'):
                    image_mime = "image/png"
                
                # Кодируем изображение в base64 для inline_data
                image_base64 = base64.b64encode(reference_image).decode('utf-8')
                
                # Создаем части с текстом и изображением через inline_data
                parts_list = [types.Part.from_text(text=prompt)]
                
                # Пробуем использовать from_bytes, если доступен, иначе через inline_data
                try:
                    # Попробуем использовать from_bytes (если такой метод есть)
                    image_part = types.Part.from_bytes(data=reference_image, mime_type=image_mime)
                    parts_list.append(image_part)
                except (AttributeError, TypeError):
                    # Если from_bytes не доступен, используем inline_data напрямую
                    inline_data_part = types.Part(
                        inline_data=types.Blob(
                            data=image_base64,
                            mime_type=image_mime
                        )
                    )
                    parts_list.append(inline_data_part)
                
                contents = [
                    types.Content(
                        role="user",
                        parts=parts_list,
                    ),
                ]
            else:
                # Только текстовый промпт
                contents = [
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(text=prompt),
                        ],
                    ),
                ]
            
            # Конфигурация для генерации изображения и текста
            generate_content_config = types.GenerateContentConfig(
                response_modalities=[
                    "IMAGE",
                    "TEXT",
                ],
            )
            
            # Генерируем контент через streaming API
            # Обертываем в executor, так как это синхронная операция, которая может блокировать event loop
            import asyncio
            image_data = None
            
            def _generate_stream():
                """Синхронная функция для генерации через streaming"""
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
            
            for chunk in chunks:
                # Проверяем наличие кандидатов и контента
                if (
                    chunk.candidates is None
                    or chunk.candidates[0].content is None
                    or chunk.candidates[0].content.parts is None
                ):
                    continue
                
                # Проверяем inline_data (изображение)
                part = chunk.candidates[0].content.parts[0]
                if part.inline_data and part.inline_data.data:
                    # Извлекаем изображение из chunk
                    data_buffer = part.inline_data.data
                    # data уже в байтах (не base64), но проверяем
                    if isinstance(data_buffer, str):
                        # Если это base64 строка, декодируем
                        image_data = base64.b64decode(data_buffer)
                    else:
                        # Если уже байты, используем напрямую
                        image_data = data_buffer
                    
                    print(f"[Генерация изображений] Изображение получено, размер: {len(image_data) if image_data else 0}")
                    # Возвращаем первое найденное изображение
                    if image_data:
                        return image_data
                else:
                    # Текстовый ответ (может быть комментарий от модели)
                    if hasattr(part, 'text') and part.text:
                        print(f"[Генерация изображений] Текстовая часть: {part.text[:100]}")
            
            # Если изображение не найдено в потоке, возвращаем None
            if not image_data:
                print("[Генерация изображений] Изображение не найдено в ответе")
            
            return image_data
            
        except Exception as e:
            error_str = str(e)
            print(f"[Генерация изображений] Ошибка: {e}")
            import traceback
            print(traceback.format_exc())
            
            # Проверяем ошибку квоты (429)
            if "429" in error_str or "quota" in error_str.lower() or "Quota exceeded" in error_str:
                # Извлекаем время ожидания из ошибки если есть
                import re
                retry_match = re.search(r'Please retry in ([\d.]+)s', error_str)
                if retry_match:
                    retry_seconds = float(retry_match.group(1))
                    raise Exception(f"Превышен лимит запросов. Попробуйте через {int(retry_seconds)} секунд.")
                else:
                    raise Exception("Превышен лимит запросов для генерации изображений. Попробуйте позже.")
            
            return None

