"""
Модуль для работы с Supabase
"""
from supabase import create_client, Client
from typing import Optional, List, Dict
import config
from uuid import UUID
import uuid

class Database:
    def __init__(self):
        self.client: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    
    def get_user(self, telegram_id: int) -> Optional[Dict]:
        """Получить пользователя по telegram_id"""
        try:
            response = self.client.table('users').select('*').eq('telegram_id', telegram_id).execute()
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Ошибка при получении пользователя: {e}")
            return None
    
    def create_user(self, telegram_id: int, active_key_id: UUID, model_name: str = 'flash') -> Optional[Dict]:
        """Создать нового пользователя"""
        try:
            data = {
                'telegram_id': telegram_id,
                'active_key_id': str(active_key_id),
                'model_name': model_name
            }
            response = self.client.table('users').insert(data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Ошибка при создании пользователя: {e}")
            return None
    
    def update_user_model(self, telegram_id: int, model_name: str) -> bool:
        """Обновить выбранную модель пользователя"""
        try:
            self.client.table('users').update({
                'model_name': model_name
            }).eq('telegram_id', telegram_id).execute()
            return True
        except Exception as e:
            print(f"Ошибка при обновлении модели пользователя: {e}")
            return False
    
    def get_user_model(self, telegram_id: int) -> str:
        """Получить выбранную модель пользователя"""
        try:
            user = self.get_user(telegram_id)
            if user and user.get('model_name'):
                return user['model_name']
            return 'flash'  # Модель по умолчанию
        except Exception as e:
            print(f"Ошибка при получении модели пользователя: {e}")
            return 'flash'
    
    def update_user_key(self, telegram_id: int, active_key_id: UUID) -> bool:
        """Обновить API-ключ пользователя"""
        try:
            self.client.table('users').update({
                'active_key_id': str(active_key_id)
            }).eq('telegram_id', telegram_id).execute()
            return True
        except Exception as e:
            print(f"Ошибка при обновлении ключа пользователя: {e}")
            return False
    
    def count_users_per_key(self, key_id: UUID) -> int:
        """Подсчитать количество пользователей на ключ"""
        try:
            response = self.client.table('users').select('telegram_id', count='exact').eq('active_key_id', str(key_id)).execute()
            # Supabase возвращает count в атрибуте count, если указан count='exact'
            if hasattr(response, 'count') and response.count is not None:
                return response.count
            # Если count не доступен, считаем вручную
            return len(response.data) if response.data else 0
        except Exception as e:
            print(f"Ошибка при подсчете пользователей: {e}")
            return 0
    
    def get_available_key(self) -> Optional[Dict]:
        """Найти доступный ключ (с менее чем MAX_USERS_PER_KEY пользователями)"""
        try:
            # Получаем все активные ключи
            keys_response = self.client.table('api_keys').select('*').eq('is_active', True).execute()
            
            for key in keys_response.data:
                key_id = UUID(key['key_id'])
                user_count = self.count_users_per_key(key_id)
                if user_count < config.MAX_USERS_PER_KEY:
                    return key
            
            return None
        except Exception as e:
            print(f"Ошибка при поиске доступного ключа: {e}")
            return None
    
    def get_all_api_keys(self) -> List[Dict]:
        """Получить все API-ключи"""
        try:
            response = self.client.table('api_keys').select('*').execute()
            return response.data if response.data else []
        except Exception as e:
            print(f"Ошибка при получении ключей: {e}")
            return []
    
    def get_api_key_by_id(self, key_id: UUID) -> Optional[Dict]:
        """Получить API-ключ по ID"""
        try:
            response = self.client.table('api_keys').select('*').eq('key_id', str(key_id)).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Ошибка при получении ключа: {e}")
            return None
    
    def get_user_chats(self, telegram_id: int) -> List[Dict]:
        """Получить все чаты пользователя"""
        try:
            response = self.client.table('chats').select('*').eq('user_id', telegram_id).order('created_at', desc=False).execute()
            return response.data if response.data else []
        except Exception as e:
            print(f"Ошибка при получении чатов: {e}")
            return []
    
    def create_chat(self, user_id: int, title: Optional[str] = None) -> Optional[Dict]:
        """Создать новый чат"""
        try:
            if title is None:
                # Подсчитываем существующие чаты для генерации названия
                existing_chats = self.get_user_chats(user_id)
                chat_number = len(existing_chats) + 1
                title = f"Чат {chat_number}"
            
            data = {
                'user_id': user_id,
                'title': title
            }
            response = self.client.table('chats').insert(data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Ошибка при создании чата: {e}")
            return None
    
    def get_chat(self, chat_id: UUID) -> Optional[Dict]:
        """Получить чат по ID"""
        try:
            response = self.client.table('chats').select('*').eq('chat_id', str(chat_id)).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Ошибка при получении чата: {e}")
            return None
    
    def update_chat_title(self, chat_id: UUID, title: str) -> bool:
        """Обновить название чата"""
        try:
            self.client.table('chats').update({'title': title}).eq('chat_id', str(chat_id)).execute()
            return True
        except Exception as e:
            print(f"Ошибка при обновлении названия чата: {e}")
            return False
    
    def set_active_chat(self, telegram_id: int, chat_id: UUID) -> bool:
        """Установить активный чат для пользователя"""
        try:
            # Обновляем пользователя, устанавливая active_chat_id
            # Если в схеме нет поля active_chat_id, используем логику: последний созданный чат считается активным
            # Для простоты просто проверяем что чат существует и принадлежит пользователю
            chat = self.get_chat(chat_id)
            if chat and chat.get('user_id') == telegram_id:
                return True
            return False
        except Exception as e:
            print(f"Ошибка при установке активного чата: {e}")
            return False
    
    def delete_chat(self, chat_id: UUID) -> bool:
        """Удалить чат (каскадное удаление сообщений)"""
        try:
            self.client.table('chats').delete().eq('chat_id', str(chat_id)).execute()
            return True
        except Exception as e:
            print(f"Ошибка при удалении чата: {e}")
            return False
    
    def get_chat_messages(self, chat_id: UUID, limit: Optional[int] = None, exclude_media: bool = False) -> List[Dict]:
        """
        Получить сообщения чата (с ограничением для контекста)
        
        Args:
            chat_id: ID чата
            limit: Ограничение количества сообщений
            exclude_media: Если True, исключает медиа-сообщения (фото, голос, файлы) из результата
        """
        try:
            query = self.client.table('messages').select('*').eq('chat_id', str(chat_id)).order('timestamp', desc=False)
            if limit:
                query = query.limit(limit * 2 if exclude_media else limit)  # Берем больше, чтобы после фильтрации было достаточно
            
            response = query.execute()
            messages = response.data if response.data else []
            
            # Исключаем медиа-сообщения если требуется
            if exclude_media:
                media_prefixes = ['[Фото]', '[Голосовое', '[PDF:', '[Текстовый файл:', '[Аудио файл:']
                messages = [
                    msg for msg in messages 
                    if not any(msg.get('content', '').startswith(prefix) for prefix in media_prefixes)
                ]
                # Ограничиваем после фильтрации
                if limit:
                    messages = messages[-limit:]
            
            return messages
        except Exception as e:
            print(f"Ошибка при получении сообщений: {e}")
            return []
    
    def add_message(self, chat_id: UUID, role: str, content: str) -> Optional[Dict]:
        """Добавить сообщение в чат"""
        try:
            data = {
                'chat_id': str(chat_id),
                'role': role,
                'content': content
            }
            response = self.client.table('messages').insert(data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Ошибка при добавлении сообщения: {e}")
            return None
    
    def get_user_active_chat(self, telegram_id: int) -> Optional[Dict]:
        """Получить активный чат пользователя (первый или последний созданный)"""
        try:
            chats = self.get_user_chats(telegram_id)
            if chats:
                # Возвращаем последний созданный чат
                return sorted(chats, key=lambda x: x['created_at'], reverse=True)[0]
            return None
        except Exception as e:
            print(f"Ошибка при получении активного чата: {e}")
            return None
    
    # Методы для работы с параметрами пользователя
    def get_user_parameters(self, telegram_id: int) -> Dict[str, str]:
        """Получить все параметры пользователя"""
        try:
            response = self.client.table('user_parameters').select('*').eq('user_id', telegram_id).execute()
            if response.data:
                return {param['parameter_key']: param['parameter_value'] for param in response.data}
            return {}
        except Exception as e:
            print(f"Ошибка при получении параметров пользователя: {e}")
            return {}
    
    def get_user_parameter(self, telegram_id: int, parameter_key: str) -> Optional[str]:
        """Получить конкретный параметр пользователя"""
        try:
            response = self.client.table('user_parameters').select('*').eq('user_id', telegram_id).eq('parameter_key', parameter_key).execute()
            if response.data:
                return response.data[0].get('parameter_value')
            return None
        except Exception as e:
            print(f"Ошибка при получении параметра пользователя: {e}")
            return None
    
    def set_user_parameter(self, telegram_id: int, parameter_key: str, parameter_value: str) -> bool:
        """Установить параметр пользователя (создать или обновить)"""
        try:
            # Используем upsert для создания или обновления
            self.client.table('user_parameters').upsert({
                'user_id': telegram_id,
                'parameter_key': parameter_key,
                'parameter_value': parameter_value
            }, on_conflict='user_id,parameter_key').execute()
            return True
        except Exception as e:
            print(f"Ошибка при установке параметра пользователя: {e}")
            return False
    
    def delete_user_parameter(self, telegram_id: int, parameter_key: str) -> bool:
        """Удалить конкретный параметр пользователя"""
        try:
            self.client.table('user_parameters').delete().eq('user_id', telegram_id).eq('parameter_key', parameter_key).execute()
            return True
        except Exception as e:
            print(f"Ошибка при удалении параметра пользователя: {e}")
            return False
    
    def clear_user_parameters(self, telegram_id: int) -> bool:
        """Очистить все параметры пользователя"""
        try:
            self.client.table('user_parameters').delete().eq('user_id', telegram_id).execute()
            return True
        except Exception as e:
            print(f"Ошибка при очистке параметров пользователя: {e}")
            return False

