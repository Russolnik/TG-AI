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
    
    def assign_key_to_user(self, telegram_id: int, username: Optional[str] = None, 
                          first_name: Optional[str] = None, photo_url: Optional[str] = None) -> Tuple[Optional[UUID], Optional[str], str]:
        """
        Назначить API-ключ пользователю
        
        Returns:
            tuple: (key_id, api_key, status_message)
            status_message: "assigned" | "limit_exceeded" | "existing_user"
        """
        # Маскируем telegram_id в логах
        masked_id = f"***{str(telegram_id)[-4:]}" if telegram_id else "неизвестен"
        
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
            # Проверяем есть ли вообще ключи
            all_keys = self.db.get_all_api_keys()
            active_keys = [k for k in all_keys if k.get('is_active')]
            print(f"[APIKeyManager] ❌ Нет доступных ключей. Всего: {len(all_keys)}, активных: {len(active_keys)}")
            
            # Проверяем конфиг
            import config
            config_keys_count = len(config.GEMINI_API_KEYS)
            print(f"[APIKeyManager] Ключей в конфиге: {config_keys_count}")
            
            return None, None, "limit_exceeded"
        
        key_id = UUID(available_key['key_id'])
        api_key = available_key.get('api_key')
        masked_key = f"***{api_key[-4:]}" if api_key else "отсутствует"
        print(f"[APIKeyManager] ✅ Найден доступный ключ для пользователя: {masked_id} (ключ: {masked_key})")
        
        # Создаем или обновляем пользователя
        if user:
            # Обновляем существующего пользователя
            self.db.update_user_key(telegram_id, key_id)
            # Обновляем данные профиля если они переданы
            if username is not None or first_name is not None or photo_url is not None:
                self.db.update_user_profile(telegram_id, username=username, first_name=first_name, photo_url=photo_url)
        else:
            # Создаем нового пользователя с моделью по умолчанию
            import config
            self.db.create_user(telegram_id, key_id, config.DEFAULT_MODEL, 
                               username=username, first_name=first_name, photo_url=photo_url)
            
            # Создаем первый чат для нового пользователя
            self.db.create_chat(telegram_id, "Чат 1")
        
        print(f"[APIKeyManager] ✅ Ключ назначен пользователю: {masked_id}")
        return key_id, api_key, "assigned"
    
    def get_user_api_key(self, telegram_id: int) -> Optional[str]:
        """Получить API-ключ пользователя"""
        try:
            # Маскируем telegram_id в логах
            masked_id = f"***{str(telegram_id)[-4:]}" if telegram_id else "неизвестен"
            
            user = self.db.get_user(telegram_id)
            if not user:
                return None
            
            if not user.get('active_key_id'):
                return None
            
            key_id = UUID(user['active_key_id'])
            key_data = self.db.get_api_key_by_id(key_id)
            
            if not key_data:
                return None
            
            if not key_data.get('is_active'):
                return None
            
            api_key = key_data.get('api_key')
            if not api_key:
                return None
            
            # Маскируем API ключ в логах
            masked_key = f"***{api_key[-4:]}" if api_key else "отсутствует"
            print(f"[APIKeyManager] ✅ Найден ключ для пользователя: {masked_id} (ключ: {masked_key})")
            return api_key
        except Exception as e:
            masked_id = f"***{str(telegram_id)[-4:]}" if telegram_id else "неизвестен"
            print(f"[APIKeyManager] Ошибка для пользователя: {masked_id}")
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

