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
    
    def analyze_image(self, image_data: bytes, user_question: str = "Что на этом изображении?") -> str:
        """
        Анализ изображения с помощью Gemini Vision
        
        Args:
            image_data: Байты изображения
            user_question: Вопрос пользователя к изображению
        
        Returns:
            Ответ модели
        """
        try:
            # Конвертируем байты в PIL Image
            image = Image.open(BytesIO(image_data))
            
            # Отправляем запрос в vision модель
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
    
    def generate_image(self, prompt: str, reference_image: Optional[bytes] = None) -> Optional[bytes]:
        """
        Генерация изображения через Imagen (nanoBanana)
        
        Args:
            prompt: Текстовое описание изображения
            reference_image: Опциональное референсное изображение (байты)
        
        Returns:
            Байты сгенерированного изображения или None при ошибке
        """
        try:
            import base64
            import traceback
            
            # Используем Imagen модель для генерации
            # Проверяем, доступна ли модель imagen в конфиге
            imagen_config = config.GEMINI_MODELS.get('imagen')
            if not imagen_config or not imagen_config.get('available', False):
                print(f"[Генерация изображений] Модель Imagen недоступна в конфиге")
                return None
            
            # Создаем модель Imagen
            imagen_model_name = imagen_config['name']
            print(f"[Генерация изображений] Используется модель: {imagen_model_name}")
            print(f"[Генерация изображений] Промпт: {prompt}")
            
            try:
                imagen_model = genai.GenerativeModel(imagen_model_name)
            except Exception as e:
                print(f"[Генерация изображений] Ошибка создания модели: {e}")
                print(traceback.format_exc())
                return None
            
            # Формируем промпт с generation_config для изображений
            try:
                # Конфигурация для генерации изображения
                generation_config = genai.types.GenerationConfig(
                    response_mime_type="image/png"  # Указываем, что хотим получить изображение
                )
                
                if reference_image:
                    # Если есть референсное изображение, используем мультимодальный запрос
                    image = Image.open(BytesIO(reference_image))
                    parts = [
                        prompt,
                        image
                    ]
                    print(f"[Генерация изображений] Отправка запроса с референсным изображением")
                    response = imagen_model.generate_content(
                        parts,
                        generation_config=generation_config
                    )
                else:
                    # Только текстовый промпт
                    print(f"[Генерация изображений] Отправка текстового запроса")
                    response = imagen_model.generate_content(
                        prompt,
                        generation_config=generation_config
                    )
            except Exception as e:
                error_str = str(e)
                # Проверяем ошибку квоты (429)
                if "429" in error_str or "quota" in error_str.lower() or "Quota exceeded" in error_str:
                    print(f"[Генерация изображений] Превышена квота API: {error_str}")
                    # Извлекаем время ожидания из ошибки если есть
                    import re
                    retry_match = re.search(r'Please retry in ([\d.]+)s', error_str)
                    if retry_match:
                        retry_seconds = float(retry_match.group(1))
                        raise Exception(f"Превышен лимит запросов. Попробуйте через {int(retry_seconds)} секунд.")
                    else:
                        raise Exception("Превышен лимит запросов для генерации изображений. Попробуйте позже.")
                print(f"[Генерация изображений] Ошибка при генерации контента: {e}")
                print(traceback.format_exc())
                return None
            
            print(f"[Генерация изображений] Получен ответ от API")
            print(f"[Генерация изображений] Тип response: {type(response)}")
            
            # При использовании response_mime_type="image/png" изображение возвращается в response.parts[0].inline_data.data
            # Проверяем сначала это
            if hasattr(response, 'parts') and response.parts:
                print(f"[Генерация изображений] Найден response.parts, количество: {len(response.parts)}")
                for i, part in enumerate(response.parts):
                    print(f"[Генерация изображений] Часть {i}: {type(part)}")
                    if hasattr(part, 'inline_data') and part.inline_data:
                        print(f"[Генерация изображений] Найдено inline_data в части {i}")
                        if hasattr(part.inline_data, 'data'):
                            print(f"[Генерация изображений] Извлечение base64 данных")
                            image_data = base64.b64decode(part.inline_data.data)
                            print(f"[Генерация изображений] Изображение извлечено из parts[{i}], размер: {len(image_data)}")
                            return image_data
                        elif hasattr(part.inline_data, 'mime_type'):
                            print(f"[Генерация изображений] MIME тип: {part.inline_data.mime_type}")
            
            # Получаем изображение из ответа
            # Проверяем прямой атрибут image (Gemini 2.5 Flash Image)
            if hasattr(response, 'image') and response.image:
                try:
                    print(f"[Генерация изображений] Найден атрибут response.image")
                    # Если это байты, возвращаем напрямую
                    if isinstance(response.image, bytes):
                        print(f"[Генерация изображений] Изображение в формате bytes, размер: {len(response.image)}")
                        return response.image
                    # Если это объект с данными, пробуем извлечь
                    if hasattr(response.image, 'data'):
                        print(f"[Генерация изображений] Извлечение данных из response.image.data")
                        return response.image.data
                except Exception as e:
                    print(f"[Генерация изображений] Ошибка при извлечении изображения из response.image: {e}")
            
            # Проверяем candidates и parts (стандартный формат Gemini)
            if response.candidates and len(response.candidates) > 0:
                candidate = response.candidates[0]
                print(f"[Генерация изображений] Проверка candidates, найдено: {len(response.candidates)}")
                if candidate.content and candidate.content.parts:
                    print(f"[Генерация изображений] Проверка parts, найдено: {len(candidate.content.parts)}")
                    for i, part in enumerate(candidate.content.parts):
                        print(f"[Генерация изображений] Часть {i}: {type(part)}")
                        # Проверяем inline_data
                        if hasattr(part, 'inline_data') and part.inline_data:
                            print(f"[Генерация изображений] Найдено inline_data")
                            if hasattr(part.inline_data, 'data'):
                                # Декодируем base64 изображение
                                print(f"[Генерация изображений] Декодирование base64 изображения")
                                image_data = base64.b64decode(part.inline_data.data)
                                print(f"[Генерация изображений] Изображение извлечено, размер: {len(image_data)}")
                                return image_data
                            elif hasattr(part.inline_data, 'mime_type'):
                                print(f"[Генерация изображений] MIME тип: {part.inline_data.mime_type}")
                        # Проверяем атрибут image
                        elif hasattr(part, 'image') and part.image:
                            print(f"[Генерация изображений] Найден атрибут part.image")
                            if hasattr(part.image, 'data'):
                                image_data = base64.b64decode(part.image.data)
                                print(f"[Генерация изображений] Изображение извлечено из part.image, размер: {len(image_data)}")
                                return image_data
                            elif isinstance(part.image, bytes):
                                print(f"[Генерация изображений] Изображение в формате bytes, размер: {len(part.image)}")
                                return part.image
                        # Проверяем текст (может содержать base64)
                        elif hasattr(part, 'text') and part.text:
                            print(f"[Генерация изображений] Найден текст в части: {part.text[:100] if len(part.text) > 100 else part.text}")
            
            # Проверяем response.text напрямую
            if hasattr(response, 'text') and response.text:
                print(f"[Генерация изображений] Найден response.text: {response.text[:100] if len(response.text) > 100 else response.text}")
            
            # Дополнительные проверки - может быть изображение в другом формате
            print("[Генерация изображений] Не удалось извлечь изображение стандартными методами")
            print(f"[Генерация изображений] Структура ответа: candidates={bool(response.candidates)}, text={bool(getattr(response, 'text', None))}")
            
            # Пробуем получить весь response как строку для отладки
            try:
                response_str = str(response)
                print(f"[Генерация изображений] Полный ответ (первые 500 символов): {response_str[:500]}")
            except:
                pass
            
            # Проверяем, может быть изображение возвращается через другой API метод
            # Для Gemini 2.5 Flash Image может потребоваться специальный метод
            try:
                # Проверяем, есть ли в response методы для получения изображения
                if hasattr(response, 'parts'):
                    print(f"[Генерация изображений] Найден response.parts")
                    for part in response.parts:
                        if hasattr(part, 'inline_data'):
                            print(f"[Генерация изображений] Найдено inline_data в parts")
                            if hasattr(part.inline_data, 'data'):
                                image_data = base64.b64decode(part.inline_data.data)
                                print(f"[Генерация изображений] Изображение извлечено из response.parts, размер: {len(image_data)}")
                                return image_data
            except Exception as e:
                print(f"[Генерация изображений] Ошибка при проверке response.parts: {e}")
            
            print("[Генерация изображений] Итог: Не удалось извлечь изображение из ответа Imagen")
            return None
            
        except Exception as e:
            print(f"[Генерация изображений] Критическая ошибка: {e}")
            import traceback
            print(traceback.format_exc())
            return None

