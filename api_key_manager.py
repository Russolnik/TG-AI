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
                          first_name: Optional[str] = None, photo_url: Optional[str] = None,
                          referrer_id: Optional[int] = None) -> Tuple[Optional[UUID], Optional[str], str]:
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
                               username=username, first_name=first_name, photo_url=photo_url,
                               referrer_id=referrer_id)
            
            # Создаем первый чат для нового пользователя
            self.db.create_chat(telegram_id, "Чат 1")
            
            # Если есть реферер, даем 3 дня подписки вместо пробного периода
            masked_referrer = f"***{str(referrer_id)[-4:]}" if referrer_id else None
            if referrer_id:
                print(f"[Referral] 🎁 Новый пользователь {masked_id} зарегистрирован по referral от {masked_referrer}")
                referral_reward_activated = self.db.activate_referral_reward(telegram_id, referrer_id)
                if referral_reward_activated:
                    print(f"[Referral] ✅ 3 дня подписки активированы для нового пользователя по referral")
                    # Отправляем уведомление пригласившему пользователю
                    self._notify_referrer(referrer_id, telegram_id)
                else:
                    print(f"[Referral] ⚠️ Не удалось активировать награду за referral")
                    # Fallback на обычный trial если referral reward не сработал
                    if self.db.can_use_trial(telegram_id):
                        self.db.activate_trial(telegram_id)
            else:
                # Активируем пробный период для нового пользователя (без referral)
                if self.db.can_use_trial(telegram_id):
                    trial_activated = self.db.activate_trial(telegram_id)
                    if trial_activated:
                        print(f"[APIKeyManager] ✅ Пробный период активирован для нового пользователя: {masked_id}")
                    else:
                        print(f"[APIKeyManager] ⚠️ Не удалось активировать пробный период для: {masked_id}")
        
        print(f"[APIKeyManager] ✅ Ключ назначен пользователю: {masked_id}")
        return key_id, api_key, "assigned"
    
    def _notify_referrer(self, referrer_id: int, new_user_id: int):
        """Отправить уведомление пригласившему пользователю о регистрации по его referral ссылке"""
        try:
            import config
            from telegram import Bot
            import threading
            
            # Получаем данные нового пользователя
            new_user = self.db.get_user(new_user_id)
            new_user_name = new_user.get('first_name', 'Пользователь') if new_user else 'Пользователь'
            
            # Получаем данные реферера
            referrer = self.db.get_user(referrer_id)
            if not referrer:
                print(f"[Referral Notification] ⚠️ Реферер {referrer_id} не найден в БД")
                return
            
            # Формируем сообщение для реферера
            message = (
                f"🎉 **Кто-то зарегистрировался по твоей referral ссылке!**\n\n"
                f"👤 **Новый пользователь:** {new_user_name}\n"
                f"🎁 **Твоя награда:** +3 дня подписки\n\n"
                f"Награда будет начислена автоматически при следующей проверке подписки."
            )
            
            # Отправляем уведомление в отдельном потоке, чтобы не блокировать основной процесс
            def send_notification():
                try:
                    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
                    # Используем синхронную отправку через run
                    import asyncio
                    asyncio.run(bot.send_message(
                        chat_id=referrer_id,
                        text=message,
                        parse_mode='Markdown'
                    ))
                    print(f"[Referral Notification] ✅ Уведомление отправлено рефереру {referrer_id}")
                except Exception as notify_error:
                    print(f"[Referral Notification] ❌ Ошибка отправки уведомления: {notify_error}")
            
            # Запускаем отправку в отдельном потоке
            thread = threading.Thread(target=send_notification, daemon=True)
            thread.start()
                
        except Exception as e:
            print(f"[Referral Notification] ❌ Общая ошибка отправки уведомления: {e}")
            import traceback
            traceback.print_exc()
    
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
    
    def cleanup_inactive_sessions(self, inactive_minutes: int = 10) -> int:
        """
        Очистить неактивные сессии - освободить ключи от пользователей, неактивных более указанного времени
        
        Args:
            inactive_minutes: Количество минут неактивности для очистки (по умолчанию 10)
        
        Returns:
            Количество освобожденных ключей
        """
        try:
            # Получаем список неактивных пользователей
            inactive_users = self.db.get_inactive_users(inactive_minutes)
            
            if not inactive_users:
                return 0
            
            freed_count = 0
            
            for user in inactive_users:
                telegram_id = user.get('telegram_id')
                active_key_id = user.get('active_key_id')
                
                if not telegram_id or not active_key_id:
                    continue
                
                # Удаляем привязку ключа к пользователю (не удаляем самого пользователя)
                try:
                    self.db.client.table('users').update({
                        'active_key_id': None
                    }).eq('telegram_id', telegram_id).execute()
                    
                    masked_id = f"***{str(telegram_id)[-4:]}"
                    print(f"[Cleanup] ✅ Освобожден ключ от неактивного пользователя: {masked_id}")
                    freed_count += 1
                except Exception as e:
                    print(f"[Cleanup] Ошибка при освобождении ключа для пользователя {telegram_id}: {e}")
            
            if freed_count > 0:
                print(f"[Cleanup] ✅ Освобождено ключей от неактивных сессий: {freed_count}")
            
            return freed_count
            
        except Exception as e:
            print(f"[Cleanup] Ошибка при очистке неактивных сессий: {e}")
            return 0

