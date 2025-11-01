"""
Обработчики для различных типов контента (голос, фото, файлы)
"""
import os
from PyPDF2 import PdfReader
from typing import Optional, List, Dict
from database import Database
from gemini_client import GeminiClient
import config

class ContentHandlers:
    def __init__(self, db: Database, gemini_client: GeminiClient):
        self.db = db
        self.gemini = gemini_client
    
    async def handle_voice(self, voice_file_path: str, user_question: Optional[str] = None, chat_history: Optional[List[Dict]] = None) -> str:
        """
        Обработка голосового сообщения через Gemini
        
        Args:
            voice_file_path: Путь к файлу голосового сообщения (.ogg)
            user_question: Дополнительный вопрос пользователя (если есть)
            chat_history: История чата для контекста
        
        Returns:
            Ответ от Gemini с транскрипцией и обработкой
        """
        try:
            # Проверяем размер файла
            file_size = os.path.getsize(voice_file_path)
            if file_size > config.MAX_FILE_SIZE:
                return f"❌ Файл слишком большой (максимум {config.MAX_FILE_SIZE / 1024 / 1024:.0f} МБ)"
            
            # Читаем аудио файл
            with open(voice_file_path, 'rb') as f:
                audio_data = f.read()
            
            # Определяем MIME тип
            mime_type = "audio/ogg"  # По умолчанию для Telegram голосовых
            
            # Отправляем в Gemini для обработки с историей чата
            # Ответ уже содержит транскрипцию и ответ, без дополнительных префиксов
            response = self.gemini.analyze_audio(audio_data, mime_type, user_question, chat_history)
            
            return response
            
        except Exception as e:
            print(f"Ошибка при обработке голоса: {e}")
            return f"Произошла ошибка при обработке голосового сообщения: {str(e)}"
    
    async def handle_photo(self, photo_data: bytes, user_caption: Optional[str] = None) -> str:
        """
        Обработка фотографии
        
        Args:
            photo_data: Байты изображения
            user_caption: Подпись пользователя к фото
        
        Returns:
            Ответ от Gemini Vision
        """
        try:
            question = user_caption if user_caption else "Что на этом изображении? Опишите подробно."
            response = self.gemini.analyze_image(photo_data, question)
            return f"📷 Анализ изображения:\n\n{response}"
        except Exception as e:
            print(f"Ошибка при обработке фото: {e}")
            return f"Произошла ошибка при анализе изображения: {str(e)}"
    
    async def handle_pdf(self, pdf_path: str, user_question: Optional[str] = None) -> str:
        """
        Обработка PDF файла
        
        Args:
            pdf_path: Путь к PDF файлу
            user_question: Вопрос пользователя к содержимому PDF
        
        Returns:
            Ответ от Gemini с анализом PDF
        """
        try:
            # Проверяем размер файла
            file_size = os.path.getsize(pdf_path)
            if file_size > config.MAX_FILE_SIZE:
                return f"❌ Файл слишком большой (максимум {config.MAX_FILE_SIZE / 1024 / 1024:.0f} МБ)"
            
            reader = PdfReader(pdf_path)
            text_content = ""
            
            # Извлекаем текст из всех страниц (ограничиваем для экономии токенов)
            max_pages = 10  # Максимум 10 страниц
            for i, page in enumerate(reader.pages[:max_pages]):
                text_content += f"\n--- Страница {i+1} ---\n"
                text_content += page.extract_text()
            
            if not text_content.strip():
                return "Не удалось извлечь текст из PDF файла."
            
            # Обрезаем текст если слишком длинный (ограничение токенов)
            max_chars = 50000  # ~12k токенов
            if len(text_content) > max_chars:
                text_content = text_content[:max_chars] + "\n\n[Текст обрезан из-за ограничения размера]"
            
            response = self.gemini.process_text_from_file(text_content, user_question)
            return f"📄 Анализ PDF файла:\n\n{response}"
        except Exception as e:
            print(f"Ошибка при обработке PDF: {e}")
            return f"Произошла ошибка при обработке PDF файла: {str(e)}"
    
    async def handle_text_file(self, file_path: str, user_question: Optional[str] = None) -> str:
        """
        Обработка текстового файла
        
        Args:
            file_path: Путь к текстовому файлу
            user_question: Вопрос пользователя к содержимому файла
        
        Returns:
            Ответ от Gemini с анализом файла
        """
        try:
            # Проверяем размер файла
            file_size = os.path.getsize(file_path)
            if file_size > config.MAX_FILE_SIZE:
                return f"❌ Файл слишком большой (максимум {config.MAX_FILE_SIZE / 1024 / 1024:.0f} МБ)"
            
            # Определяем кодировку и читаем файл
            encodings = ['utf-8', 'windows-1251', 'cp1252', 'latin-1']
            text_content = None
            
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        text_content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            
            if not text_content:
                return "Не удалось прочитать текстовый файл (проблема с кодировкой)."
            
            # Обрезаем если слишком длинный
            max_chars = 50000
            if len(text_content) > max_chars:
                text_content = text_content[:max_chars] + "\n\n[Текст обрезан из-за ограничения размера]"
            
            response = self.gemini.process_text_from_file(text_content, user_question)
            return f"📝 Анализ файла:\n\n{response}"
        except Exception as e:
            print(f"Ошибка при обработке текстового файла: {e}")
            return f"Произошла ошибка при обработке файла: {str(e)}"
    
    async def handle_audio_file(self, audio_path: str, user_question: Optional[str] = None) -> str:
        """
        Обработка аудио файла через Gemini
        
        Args:
            audio_path: Путь к аудио файлу
            user_question: Вопрос пользователя к содержимому аудио
        
        Returns:
            Ответ от Gemini с транскрипцией и обработкой
        """
        try:
            # Проверяем размер файла
            file_size = os.path.getsize(audio_path)
            if file_size > config.MAX_FILE_SIZE:
                return f"❌ Файл слишком большой (максимум {config.MAX_FILE_SIZE / 1024 / 1024:.0f} МБ)"
            
            # Читаем аудио файл
            with open(audio_path, 'rb') as f:
                audio_data = f.read()
            
            # Определяем MIME тип
            if audio_path.endswith('.mp3'):
                mime_type = "audio/mpeg"
            elif audio_path.endswith('.wav'):
                mime_type = "audio/wav"
            elif audio_path.endswith('.ogg'):
                mime_type = "audio/ogg"
            elif audio_path.endswith('.m4a'):
                mime_type = "audio/mp4"
            elif audio_path.endswith('.flac'):
                mime_type = "audio/flac"
            else:
                mime_type = "audio/mpeg"
            
            # Отправляем в Gemini
            response = self.gemini.analyze_audio(audio_data, mime_type, user_question)
            return f"🎵 Аудио файл обработан:\n\n{response}"
                
        except Exception as e:
            print(f"Ошибка при обработке аудио файла: {e}")
            return f"Произошла ошибка при обработке аудио файла: {str(e)}"
    
    async def handle_generate_image(self, prompt: str, reference_image: Optional[bytes] = None) -> Optional[bytes]:
        """
        Генерация изображения через Imagen
        
        Args:
            prompt: Текстовое описание изображения
            reference_image: Опциональное референсное изображение
        
        Returns:
            Байты сгенерированного изображения или None при ошибке
        """
        try:
            image_data = self.gemini.generate_image(prompt, reference_image)
            return image_data
        except Exception as e:
            print(f"Ошибка при генерации изображения: {e}")
            return None

