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

# Настройка транспорта для Gemini API с учетом региона
def _configure_gemini_transport():
    """Настройка транспорта для Gemini API с правильным регионом"""
    # Базовая конфигурация клиента
    # Все запросы идут с сервера, а не с клиента
    
    # Если указан proxy, используем его для обхода географических ограничений
    if config.GEMINI_PROXY_URL:
        # Настройка proxy для httpx (используется внутренне библиотекой google-generativeai)
        os.environ['HTTP_PROXY'] = config.GEMINI_PROXY_URL
        os.environ['HTTPS_PROXY'] = config.GEMINI_PROXY_URL
        print(f"Используется proxy для Gemini API: {config.GEMINI_PROXY_URL}")

class GeminiClient:
    def __init__(self, api_key: str, model_name: str = 'flash'):
        """
        Инициализация клиента Gemini
        
        Args:
            api_key: API ключ Gemini
            model_name: Имя модели из config.GEMINI_MODELS (flash, pro, flash-latest)
        """
        # Настройка с учетом региона и локации
        # Все запросы к Gemini API идут с сервера, что решает проблему "User location is not supported"
        try:
            # Настраиваем proxy если указан (для обхода географических ограничений)
            _configure_gemini_transport()
            
            # Базовая конфигурация - запросы всегда идут с сервера, где запущен бот
            genai.configure(api_key=api_key)
        except Exception as e:
            print(f"Предупреждение: не удалось настроить транспорт для Gemini API: {e}")
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
            
            # Преобразуем историю в формат для Gemini
            # Gemini использует чередующиеся сообщения user/model
            chat_history = []
            for msg in messages:
                role = "user" if msg['role'] == 'user' else "model"
                chat_history.append({
                    'role': role,
                    'parts': [{'text': msg['content']}]
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

