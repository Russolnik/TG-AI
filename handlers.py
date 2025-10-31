"""
Обработчики для различных типов контента (голос, фото, файлы)
"""
import os
import whisper
from pydub import AudioSegment
from PyPDF2 import PdfReader
from typing import Optional
from database import Database
from gemini_client import GeminiClient
import config
import tempfile

# Настройка пути к FFmpeg
def _setup_ffmpeg_path():
    """Настройка пути к FFmpeg"""
    if config.FFMPEG_PATH and os.path.exists(config.FFMPEG_PATH):
        # Устанавливаем путь к FFmpeg для pydub
        AudioSegment.converter = config.FFMPEG_PATH
        AudioSegment.ffmpeg = config.FFMPEG_PATH
        AudioSegment.ffprobe = config.FFMPEG_PATH.replace('ffmpeg', 'ffprobe')
    else:
        # Пробуем найти FFmpeg в директории проекта
        project_dir = os.path.dirname(os.path.abspath(__file__))
        possible_paths = [
            os.path.join(project_dir, 'ffmpeg', 'bin', 'ffmpeg.exe'),
            os.path.join(project_dir, 'ffmpeg.exe'),
            os.path.join(project_dir, 'ffmpeg-8.0', 'bin', 'ffmpeg.exe'),
            os.path.join(project_dir, 'ffmpeg-8.0', 'ffmpeg.exe'),
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                AudioSegment.converter = path
                AudioSegment.ffmpeg = path
                # Пробуем найти ffprobe
                ffprobe_path = path.replace('ffmpeg', 'ffprobe')
                if os.path.exists(ffprobe_path):
                    AudioSegment.ffprobe = ffprobe_path
                print(f"FFmpeg найден: {path}")
                return
        
        # Если не найден, используем системный FFmpeg
        print("Используется системный FFmpeg (должен быть в PATH)")

# Инициализация пути к FFmpeg при импорте модуля
_setup_ffmpeg_path()

class ContentHandlers:
    def __init__(self, db: Database, gemini_client: GeminiClient):
        self.db = db
        self.gemini = gemini_client
        self.whisper_model = None  # Ленивая загрузка модели Whisper
    
    def _load_whisper_model(self):
        """Ленивая загрузка модели Whisper"""
        if self.whisper_model is None:
            print("Загрузка модели Whisper...")
            self.whisper_model = whisper.load_model("base")
            print("Модель Whisper загружена")
    
    async def handle_voice(self, voice_file_path: str, user_question: Optional[str] = None) -> str:
        """
        Обработка голосового сообщения
        
        Args:
            voice_file_path: Путь к файлу голосового сообщения (.ogg)
            user_question: Дополнительный вопрос пользователя (если есть)
        
        Returns:
            Транскрибированный текст и ответ от Gemini
        """
        try:
            # Ленивая загрузка модели
            self._load_whisper_model()
            
            # Конвертируем .ogg в .wav для Whisper
            audio = AudioSegment.from_ogg(voice_file_path)
            
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                audio.export(tmp_file.name, format='wav')
                temp_wav_path = tmp_file.name
            
            try:
                # Транскрибация
                result = self.whisper_model.transcribe(temp_wav_path)
                transcribed_text = result["text"]
                
                if not transcribed_text.strip():
                    return "Не удалось распознать речь в голосовом сообщении."
                
                # Если есть дополнительный вопрос, объединяем его с транскрипцией
                if user_question:
                    final_prompt = f"Пользователь задал вопрос: {user_question}\n\nТакже прислал голосовое сообщение, которое было транскрибировано:\n{transcribed_text}\n\nОтветьте на вопрос пользователя, учитывая содержание голосового сообщения."
                else:
                    final_prompt = f"Пользователь прислал голосовое сообщение. Транскрипция:\n{transcribed_text}\n\nОбработайте это сообщение."
                
                # Отправляем в Gemini
                response = self.gemini.chat([{"role": "user", "content": final_prompt}])
                
                return f"🎙️ Транскрибировано: {transcribed_text}\n\n💬 Ответ:\n{response}"
            finally:
                # Удаляем временный файл
                if os.path.exists(temp_wav_path):
                    os.unlink(temp_wav_path)
                
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
        Обработка аудио файла (MP3 и другие форматы)
        
        Args:
            audio_path: Путь к аудио файлу
            user_question: Вопрос пользователя к содержимому аудио
        
        Returns:
            Транскрибированный текст и ответ от Gemini
        """
        try:
            # Используем ту же логику, что и для голоса
            self._load_whisper_model()
            
            # Конвертируем в wav для Whisper
            audio = AudioSegment.from_file(audio_path)
            
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                audio.export(tmp_file.name, format='wav')
                temp_wav_path = tmp_file.name
            
            try:
                # Транскрибация
                result = self.whisper_model.transcribe(temp_wav_path)
                transcribed_text = result["text"]
                
                if not transcribed_text.strip():
                    return "Не удалось распознать речь в аудио файле."
                
                if user_question:
                    final_prompt = f"Пользователь задал вопрос: {user_question}\n\nТакже прислал аудио файл, которое было транскрибировано:\n{transcribed_text}\n\nОтветьте на вопрос пользователя, учитывая содержание аудио."
                else:
                    final_prompt = f"Пользователь прислал аудио файл. Транскрипция:\n{transcribed_text}\n\nОбработайте это сообщение."
                
                response = self.gemini.chat([{"role": "user", "content": final_prompt}])
                return f"🎵 Транскрибировано из аудио:\n{transcribed_text}\n\n💬 Ответ:\n{response}"
            finally:
                if os.path.exists(temp_wav_path):
                    os.unlink(temp_wav_path)
                
        except Exception as e:
            print(f"Ошибка при обработке аудио файла: {e}")
            return f"Произошла ошибка при обработке аудио файла: {str(e)}"

