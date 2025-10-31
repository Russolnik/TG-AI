"""
Модуль управления API-ключами Gemini
"""
from typing import Optional, Tuple
from uuid import UUID
import config
from database import Database
import uuid

class APIKeyManager:
    def __init__(self, db: Database):
        self.db = db
        self._initialize_keys()
    
    def _initialize_keys(self):
        """Инициализация ключей в базе данных при первом запуске"""
        existing_keys = self.db.get_all_api_keys()
        existing_key_values = {key['api_key'] for key in existing_keys}
        
        # Добавляем новые ключи, которых еще нет в БД
        for api_key in config.GEMINI_API_KEYS:
            if api_key not in existing_key_values:
                try:
                    self.db.client.table('api_keys').insert({
                        'api_key': api_key,
                        'is_active': True
                    }).execute()
                    print(f"Добавлен новый API-ключ в БД")
                except Exception as e:
                    print(f"Ошибка при добавлении ключа: {e}")
    
    def assign_key_to_user(self, telegram_id: int) -> Tuple[Optional[UUID], Optional[str], str]:
        """
        Назначить API-ключ пользователю
        
        Returns:
            tuple: (key_id, api_key, status_message)
            status_message: "assigned" | "limit_exceeded" | "existing_user"
        """
        # Проверяем, существует ли пользователь
        user = self.db.get_user(telegram_id)
        
        if user and user.get('active_key_id'):
            # Пользователь уже существует и имеет ключ
            key_id = UUID(user['active_key_id'])
            key_data = self.db.get_api_key_by_id(key_id)
            if key_data:
                return key_id, key_data['api_key'], "existing_user"
        
        # Ищем доступный ключ
        available_key = self.db.get_available_key()
        
        if not available_key:
            return None, None, "limit_exceeded"
        
        key_id = UUID(available_key['key_id'])
        
            # Создаем или обновляем пользователя
        if user:
            # Обновляем существующего пользователя
            self.db.update_user_key(telegram_id, key_id)
        else:
            # Создаем нового пользователя с моделью по умолчанию
            import config
            self.db.create_user(telegram_id, key_id, config.DEFAULT_MODEL)
            
            # Создаем первый чат для нового пользователя
            self.db.create_chat(telegram_id, "Чат 1")
        
        return key_id, available_key['api_key'], "assigned"
    
    def get_user_api_key(self, telegram_id: int) -> Optional[str]:
        """Получить API-ключ пользователя"""
        user = self.db.get_user(telegram_id)
        if not user or not user.get('active_key_id'):
            return None
        
        key_id = UUID(user['active_key_id'])
        key_data = self.db.get_api_key_by_id(key_id)
        
        if key_data and key_data.get('is_active'):
            return key_data['api_key']
        
        return None
    
    def deactivate_key(self, key_id: UUID) -> bool:
        """Деактивировать API-ключ"""
        try:
            self.db.client.table('api_keys').update({
                'is_active': False
            }).eq('key_id', str(key_id)).execute()
            return True
        except Exception as e:
            print(f"Ошибка при деактивации ключа: {e}")
            return False
    
    def get_key_usage_stats(self) -> dict:
        """Получить статистику использования ключей"""
        keys = self.db.get_all_api_keys()
        stats = []
        
        for key in keys:
            key_id = UUID(key['key_id'])
            user_count = self.db.count_users_per_key(key_id)
            stats.append({
                'key_id': key['key_id'],
                'is_active': key['is_active'],
                'user_count': user_count,
                'max_users': config.MAX_USERS_PER_KEY
            })
        
        return stats

