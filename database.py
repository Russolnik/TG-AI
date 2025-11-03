"""
Модуль для работы с Supabase
"""
from supabase import create_client, Client
from typing import Optional, List, Dict, Any
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
    
    def create_user(self, telegram_id: int, active_key_id: UUID, model_name: str = 'flash-lite', 
                   username: Optional[str] = None, first_name: Optional[str] = None, 
                   photo_url: Optional[str] = None, referrer_id: Optional[int] = None) -> Optional[Dict]:
        """Создать нового пользователя"""
        try:
            import secrets
            import string
            
            data = {
                'telegram_id': telegram_id,
                'active_key_id': str(active_key_id),
                'model_name': model_name
            }
            # Добавляем данные профиля если они есть
            if username:
                data['username'] = username
            if first_name:
                data['first_name'] = first_name
            if photo_url:
                data['photo_url'] = photo_url
            
            # Генерируем уникальный referral код для нового пользователя
            # Формат: ref_<telegram_id>_<случайная строка> или просто ref_<telegram_id>
            referral_code = f"ref_{telegram_id}"
            data['referral_code'] = referral_code
            
            # Сохраняем ID реферера если есть
            if referrer_id:
                data['referrer_id'] = referrer_id
            
            response = self.client.table('users').insert(data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Ошибка при создании пользователя: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def update_user_profile(self, telegram_id: int, username: Optional[str] = None, 
                           first_name: Optional[str] = None, photo_url: Optional[str] = None) -> bool:
        """Обновить данные профиля пользователя"""
        try:
            update_data = {}
            if username is not None:
                update_data['username'] = username
            if first_name is not None:
                update_data['first_name'] = first_name
            if photo_url is not None:
                update_data['photo_url'] = photo_url
            
            if update_data:
                self.client.table('users').update(update_data).eq('telegram_id', telegram_id).execute()
            return True
        except Exception as e:
            print(f"Ошибка при обновлении профиля пользователя: {e}")
            return False
    
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
            return 'flash-lite'  # Модель по умолчанию - Flash Lite для быстрых ответов
        except Exception as e:
            print(f"Ошибка при получении модели пользователя: {e}")
            return 'flash-lite'
    
    def update_user_key(self, telegram_id: int, active_key_id: UUID) -> bool:
        """Обновить API-ключ пользователя"""
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            self.client.table('users').update({
                'active_key_id': str(active_key_id),
                'last_activity': now.isoformat()
            }).eq('telegram_id', telegram_id).execute()
            return True
        except Exception as e:
            print(f"Ошибка при обновлении ключа пользователя: {e}")
            return False
    
    def update_user_activity(self, telegram_id: int) -> bool:
        """Обновить время последней активности пользователя"""
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            self.client.table('users').update({
                'last_activity': now.isoformat()
            }).eq('telegram_id', telegram_id).execute()
            return True
        except Exception as e:
            print(f"Ошибка при обновлении активности пользователя: {e}")
            return False
    
    def get_inactive_users(self, inactive_minutes: int = 10) -> List[Dict]:
        """Получить список неактивных пользователей (неактивны более указанного количества минут)"""
        try:
            from datetime import datetime, timezone, timedelta
            cutoff_time = (datetime.now(timezone.utc) - timedelta(minutes=inactive_minutes)).isoformat()
            
            response = self.client.table('users').select('*').lt('last_activity', cutoff_time).execute()
            return response.data if response.data else []
        except Exception as e:
            print(f"Ошибка при получении неактивных пользователей: {e}")
            return []
    
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
    
    def create_chat(self, user_id: int, title: Optional[str] = None, chat_type: Optional[str] = None) -> Optional[Dict]:
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
            
            # Добавляем тип чата если указан
            if chat_type:
                data['chat_type'] = chat_type
            
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
    
    def add_message(self, chat_id: UUID, role: str, content: str, context_type: Optional[str] = None) -> Optional[Dict]:
        """Добавить сообщение в чат"""
        try:
            data = {
                'chat_id': str(chat_id),
                'role': role,
                'content': content
            }
            
            # Добавляем тип контекста если указан
            if context_type:
                data['context_type'] = context_type
            
            response = self.client.table('messages').insert(data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Ошибка при добавлении сообщения: {e}")
            return None
    
    def update_chat_context(self, chat_id: UUID, context_summary: str) -> bool:
        """Обновить контекст чата (краткое описание)"""
        try:
            self.client.table('chats').update({
                'context_summary': context_summary
            }).eq('chat_id', str(chat_id)).execute()
            return True
        except Exception as e:
            print(f"Ошибка при обновлении контекста чата: {e}")
            return False
    
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
    
    # Методы для работы с подписками
    def get_active_subscription(self, telegram_id: int) -> Optional[Dict]:
        """Получить активную подписку пользователя"""
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            
            response = self.client.table('subscriptions').select('*').eq('user_id', telegram_id).eq('is_active', True).gte('end_date', now.isoformat()).order('end_date', desc=True).limit(1).execute()
            subscription = response.data[0] if response.data else None
            
            # Добавляем расчет процента использования для подписок на 3-6 месяцев
            if subscription:
                start_date = datetime.fromisoformat(subscription['start_date'].replace('Z', '+00:00'))
                end_date = datetime.fromisoformat(subscription['end_date'].replace('Z', '+00:00'))
                subscription_type = subscription.get('subscription_type', '')
                
                # Определяем количество месяцев подписки
                months_map = {
                    '1_month': 1,
                    '3_months': 3,
                    '6_months': 6
                }
                months = months_map.get(subscription_type, 1)
                
                if months >= 3:
                    total_duration = (end_date - start_date).total_seconds()
                    used_duration = (now - start_date).total_seconds()
                    usage_percent = min(100, max(0, (used_duration / total_duration) * 100)) if total_duration > 0 else 0
                    subscription['usage_percent'] = round(usage_percent, 2)
                    
                    # Расчет возможного возврата: максимум 50% от неиспользованного периода
                    unused_percent = 100 - usage_percent
                    refund_percent = min(50, unused_percent * 0.5)  # Максимум 50% от неиспользованного
                    subscription['refund_percent'] = round(refund_percent, 2)
            
            return subscription
        except Exception as e:
            print(f"Ошибка при получении активной подписки: {e}")
            return None
    
    def create_subscription(self, telegram_id: int, subscription_type: str, payment_charge_id: Optional[str] = None) -> Optional[Dict]:
        """Создать или продлить подписку для пользователя"""
        try:
            from datetime import datetime, timezone, timedelta
            import dateutil.parser
            
            # Определяем срок подписки
            months = {'1_month': 1, '3_months': 3, '6_months': 6}
            months_count = months.get(subscription_type, 1)
            
            now = datetime.now(timezone.utc)
            
            # Проверяем активный trial и добавляем оставшееся время к подписке
            trial_hours_to_add = 0
            user = self.get_user(telegram_id)
            if user:
                trial_start = user.get('trial_start')
                trial_used = user.get('trial_used', False)
                
                # Проверяем trial только если он еще не был использован
                if trial_start and not trial_used:
                    if self.is_trial_active(telegram_id):
                        # Вычисляем оставшиеся часы trial
                        try:
                            if isinstance(trial_start, str):
                                trial_start_dt = dateutil.parser.parse(trial_start)
                            else:
                                trial_start_dt = trial_start
                            
                            if trial_start_dt.tzinfo is None:
                                trial_start_dt = trial_start_dt.replace(tzinfo=timezone.utc)
                            
                            trial_end = trial_start_dt + timedelta(hours=24)
                            if trial_end > now:
                                trial_hours_to_add = (trial_end - now).total_seconds() / 3600
                                trial_hours_to_add = max(0, trial_hours_to_add)
                                print(f"[Create Subscription] ⏰ Добавляем {trial_hours_to_add:.2f} часов из активного trial к подписке")
                        except Exception as e:
                            print(f"Ошибка при вычислении оставшихся часов trial: {e}")
                    
                    # Помечаем trial как использованный только если он был активен
                    if trial_hours_to_add > 0:
                        self.client.table('users').update({
                            'trial_used': True
                        }).eq('telegram_id', telegram_id).execute()
                        print(f"[Create Subscription] ✅ Trial помечен как использованный")
            
            # Проверяем, есть ли уже активная подписка
            existing_subscription = self.get_active_subscription(telegram_id)
            
            if existing_subscription:
                # Если есть активная подписка, продлеваем её
                existing_end_date = datetime.fromisoformat(existing_subscription['end_date'].replace('Z', '+00:00'))
                
                # Если текущая подписка еще не истекла, продлеваем от даты окончания
                if existing_end_date > now:
                    new_end_date = existing_end_date + timedelta(days=months_count * 30)
                    # Добавляем оставшиеся часы trial
                    if trial_hours_to_add > 0:
                        new_end_date = new_end_date + timedelta(hours=trial_hours_to_add)
                    start_date = existing_subscription['start_date']
                else:
                    # Если подписка истекла, начинаем с сегодня + оставшиеся часы trial
                    new_end_date = now + timedelta(days=months_count * 30)
                    if trial_hours_to_add > 0:
                        new_end_date = new_end_date + timedelta(hours=trial_hours_to_add)
                    start_date = now.isoformat()
                
                # Обновляем существующую подписку
                update_data = {
                    'end_date': new_end_date.isoformat(),
                    'subscription_type': subscription_type,  # Обновляем тип подписки
                    'is_active': True,
                    'updated_at': now.isoformat()
                }
                
                # Добавляем payment_charge_id если есть
                if payment_charge_id:
                    update_data['payment_charge_id'] = payment_charge_id
                
                # Получаем ID подписки (может быть subscription_id или id)
                subscription_id_field = None
                subscription_id_value = None
                
                if 'id' in existing_subscription:
                    subscription_id_field = 'id'
                    subscription_id_value = existing_subscription['id']
                elif 'subscription_id' in existing_subscription:
                    subscription_id_field = 'subscription_id'
                    subscription_id_value = existing_subscription['subscription_id']
                
                if subscription_id_field and subscription_id_value:
                    # Обновляем существующую подписку по найденному полю
                    try:
                        response = self.client.table('subscriptions').update(update_data).eq(subscription_id_field, subscription_id_value).execute()
                    except Exception as e:
                        print(f"[Create Subscription] ⚠️ Ошибка обновления по {subscription_id_field}: {e}")
                        response = None
                    
                    # Если не сработало, пробуем обновить по user_id
                    if not response or not response.data or len(response.data) == 0:
                        try:
                            response = self.client.table('subscriptions').update(update_data).eq('user_id', telegram_id).eq('is_active', True).execute()
                        except Exception as e:
                            print(f"[Create Subscription] ⚠️ Ошибка обновления по user_id: {e}")
                            response = None
                else:
                    # Если нет ID, пробуем обновить по user_id напрямую
                    try:
                        response = self.client.table('subscriptions').update(update_data).eq('user_id', telegram_id).eq('is_active', True).execute()
                    except Exception as e:
                        print(f"[Create Subscription] ⚠️ Ошибка обновления по user_id: {e}")
                        response = None
                
                # Если обновление не сработало, создаем новую подписку
                if not response or not response.data or len(response.data) == 0:
                    # Пробуем найти подписку по user_id для отладки
                    try:
                        found_response = self.client.table('subscriptions').select('*').eq('user_id', telegram_id).eq('is_active', True).order('end_date', desc=True).limit(1).execute()
                        if found_response.data and len(found_response.data) > 0:
                            print(f"[Create Subscription] ⚠️ Подписка найдена, но обновление не сработало. Создаем новую.")
                    except:
                        pass
                    return self._create_new_subscription(telegram_id, subscription_type, payment_charge_id, now, new_end_date)
                
                if response.data and len(response.data) > 0:
                    return response.data[0]
                else:
                    # Fallback: создаем новую подписку если обновление не сработало
                    end_date = now + timedelta(days=months_count * 30)
                    if trial_hours_to_add > 0:
                        end_date = end_date + timedelta(hours=trial_hours_to_add)
                    return self._create_new_subscription(telegram_id, subscription_type, payment_charge_id, now, end_date)
            else:
                # Если нет активной подписки, создаем новую
                end_date = now + timedelta(days=months_count * 30)
                if trial_hours_to_add > 0:
                    end_date = end_date + timedelta(hours=trial_hours_to_add)
                return self._create_new_subscription(telegram_id, subscription_type, payment_charge_id, now, end_date)
        except Exception as e:
            print(f"Ошибка при создании/продлении подписки: {e}")
            return None
    
    def _create_new_subscription(self, telegram_id: int, subscription_type: str, payment_charge_id: Optional[str], start_date: Any, end_date: Any) -> Optional[Dict]:
        """Вспомогательный метод для создания новой подписки"""
        try:
            # НЕ деактивируем активные подписки при создании новой - это делается только при обновлении существующей
            # Деактивируем только неактивные подписки для чистоты БД (опционально)
            
            # Создаем новую подписку
            # start_date и end_date должны быть datetime объектами
            start_date_str = start_date.isoformat() if hasattr(start_date, 'isoformat') else str(start_date)
            end_date_str = end_date.isoformat() if hasattr(end_date, 'isoformat') else str(end_date)
            
            data = {
                'user_id': telegram_id,
                'subscription_type': subscription_type,
                'start_date': start_date_str,
                'end_date': end_date_str,
                'is_active': True,
                'auto_renew': False
            }
            
            # Добавляем payment_charge_id если есть (для возвратов Stars)
            if payment_charge_id:
                data['payment_charge_id'] = payment_charge_id
            
            response = self.client.table('subscriptions').insert(data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Ошибка при создании новой подписки: {e}")
            return None
    
    def deactivate_subscription(self, telegram_id: int) -> bool:
        """Деактивировать активную подписку пользователя"""
        try:
            self.client.table('subscriptions').update({
                'is_active': False,
                'auto_renew': False
            }).eq('user_id', telegram_id).eq('is_active', True).execute()
            return True
        except Exception as e:
            print(f"Ошибка при деактивации подписки: {e}")
            return False
    
    def cancel_subscription(self, telegram_id: int) -> bool:
        """Отменить активную подписку пользователя"""
        try:
            self.client.table('subscriptions').update({'is_active': False, 'auto_renew': False}).eq('user_id', telegram_id).eq('is_active', True).execute()
            return True
        except Exception as e:
            print(f"Ошибка при отмене подписки: {e}")
            return False
    
    def pause_subscription(self, telegram_id: int) -> bool:
        """Приостановить подписку (установить is_active=False, но сохранить end_date)"""
        try:
            self.client.table('subscriptions').update({'is_active': False}).eq('user_id', telegram_id).eq('is_active', True).execute()
            return True
        except Exception as e:
            print(f"Ошибка при приостановке подписки: {e}")
            return False
    
    def resume_subscription(self, telegram_id: int) -> bool:
        """Возобновить подписку (установить is_active=True)"""
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            
            # Находим подписку пользователя (неактивную, но с будущей end_date)
            response = self.client.table('subscriptions').select('*').eq('user_id', telegram_id).eq('is_active', False).gte('end_date', now.isoformat()).order('end_date', desc=True).limit(1).execute()
            
            if response.data:
                subscription = response.data[0]
                # Возобновляем только если end_date еще не истек
                self.client.table('subscriptions').update({'is_active': True}).eq('id', subscription.get('id') or subscription.get('subscription_id')).execute()
                return True
            return False
        except Exception as e:
            print(f"Ошибка при возобновлении подписки: {e}")
            return False
    
    def get_user_subscriptions(self, telegram_id: int) -> List[Dict]:
        """Получить все подписки пользователя (включая неактивные)"""
        try:
            response = self.client.table('subscriptions').select('*').eq('user_id', telegram_id).order('created_at', desc=True).execute()
            return response.data if response.data else []
        except Exception as e:
            print(f"Ошибка при получении подписок пользователя: {e}")
            return []
    
    def admin_create_subscription(self, telegram_id: int, subscription_type: str, months: Optional[int] = None) -> Optional[Dict]:
        """Административный метод для создания подписки (можно указать кастомное количество месяцев)"""
        try:
            from datetime import datetime, timezone, timedelta
            import dateutil.parser
            
            # Определяем срок подписки
            if months:
                months_count = months
            else:
                months_map = {'1_month': 1, '3_months': 3, '6_months': 6}
                months_count = months_map.get(subscription_type, 1)
            
            now = datetime.now(timezone.utc)
            
            # Проверяем активный trial и добавляем оставшееся время к подписке
            trial_hours_to_add = 0
            user = self.get_user(telegram_id)
            if user:
                trial_start = user.get('trial_start')
                trial_used = user.get('trial_used', False)
                
                # Проверяем trial только если он еще не был использован
                if trial_start and not trial_used:
                    if self.is_trial_active(telegram_id):
                        # Вычисляем оставшиеся часы trial
                        try:
                            if isinstance(trial_start, str):
                                trial_start_dt = dateutil.parser.parse(trial_start)
                            else:
                                trial_start_dt = trial_start
                            
                            if trial_start_dt.tzinfo is None:
                                trial_start_dt = trial_start_dt.replace(tzinfo=timezone.utc)
                            
                            trial_end = trial_start_dt + timedelta(hours=24)
                            if trial_end > now:
                                trial_hours_to_add = (trial_end - now).total_seconds() / 3600
                                trial_hours_to_add = max(0, trial_hours_to_add)
                                print(f"[Admin Create Subscription] ⏰ Добавляем {trial_hours_to_add:.2f} часов из активного trial к подписке")
                        except Exception as e:
                            print(f"Ошибка при вычислении оставшихся часов trial: {e}")
                    
                    # Помечаем trial как использованный только если он был активен
                    if trial_hours_to_add > 0:
                        self.client.table('users').update({
                            'trial_used': True
                        }).eq('telegram_id', telegram_id).execute()
                        print(f"[Admin Create Subscription] ✅ Trial помечен как использованный")
            
            # Проверяем, есть ли активная подписка для продления
            existing_subscription = self.get_active_subscription(telegram_id)
            
            if existing_subscription:
                # Продлеваем существующую подписку
                existing_end_date = datetime.fromisoformat(existing_subscription['end_date'].replace('Z', '+00:00'))
                if existing_end_date > now:
                    new_end_date = existing_end_date + timedelta(days=months_count * 30)
                else:
                    new_end_date = now + timedelta(days=months_count * 30)
                
                # Добавляем оставшиеся часы trial
                if trial_hours_to_add > 0:
                    new_end_date = new_end_date + timedelta(hours=trial_hours_to_add)
                
                # Получаем ID подписки из найденной записи (может быть любое поле, которое является первичным ключом)
                # В Supabase обычно это автоматически генерируемое поле, проверяем несколько вариантов
                subscription_id_field = None
                subscription_id_value = None
                
                # Пробуем разные варианты полей-идентификаторов
                if 'id' in existing_subscription:
                    subscription_id_field = 'id'
                    subscription_id_value = existing_subscription['id']
                elif 'subscription_id' in existing_subscription:
                    subscription_id_field = 'subscription_id'
                    subscription_id_value = existing_subscription['subscription_id']
                else:
                    # Если нет явного ID, ищем по user_id и обновляем напрямую
                    response = self.client.table('subscriptions').update({
                        'end_date': new_end_date.isoformat(),
                        'subscription_type': subscription_type,
                        'is_active': True,
                        'updated_at': now.isoformat()
                    }).eq('user_id', telegram_id).eq('is_active', True).order('end_date', desc=True).limit(1).execute()
                    
                    if response.data and len(response.data) > 0:
                        print(f"[Admin Create Subscription] ✅ Подписка обновлена по user_id")
                        return response.data[0]
                
                if subscription_id_field and subscription_id_value:
                    # Обновляем по найденному полю-идентификатору
                    try:
                        response = self.client.table('subscriptions').update({
                            'end_date': new_end_date.isoformat(),
                            'subscription_type': subscription_type,
                            'is_active': True,
                            'updated_at': now.isoformat()
                        }).eq(subscription_id_field, subscription_id_value).execute()
                        
                        if response.data and len(response.data) > 0:
                            print(f"[Admin Create Subscription] ✅ Подписка обновлена по {subscription_id_field}")
                            return response.data[0]
                    except Exception as e:
                        print(f"[Admin Create Subscription] ⚠️ Ошибка обновления по {subscription_id_field}: {e}")
                        # Пробуем альтернативный способ - обновление по user_id
                        pass
                    
                    # Fallback: обновляем по user_id если обновление по ID не сработало
                    try:
                        response = self.client.table('subscriptions').update({
                            'end_date': new_end_date.isoformat(),
                            'subscription_type': subscription_type,
                            'is_active': True,
                            'updated_at': now.isoformat()
                        }).eq('user_id', telegram_id).eq('is_active', True).execute()
                        
                        if response.data and len(response.data) > 0:
                            print(f"[Admin Create Subscription] ✅ Подписка обновлена через fallback по user_id")
                            return response.data[0]
                    except Exception as e:
                        print(f"[Admin Create Subscription] ⚠️ Ошибка fallback обновления: {e}")
            
            # Если не удалось обновить существующую, создаем новую подписку
            print(f"[Admin Create Subscription] Создаем новую подписку для user_id: {telegram_id}")
            end_date = now + timedelta(days=months_count * 30)
            # Добавляем оставшиеся часы trial
            if trial_hours_to_add > 0:
                end_date = end_date + timedelta(hours=trial_hours_to_add)
            
            new_sub = self._create_new_subscription(telegram_id, subscription_type, None, now, end_date)
            if new_sub:
                print(f"[Admin Create Subscription] ✅ Новая подписка создана")
            else:
                print(f"[Admin Create Subscription] ❌ Ошибка при создании новой подписки")
            return new_sub
        except Exception as e:
            print(f"Ошибка при административном создании подписки: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def has_active_subscription(self, telegram_id: int, username: Optional[str] = None) -> bool:
        """Проверить, есть ли у пользователя активная подписка (включая пробный период)"""
        try:
            # Специальная проверка для @rusolnik - вечная подписка
            if username and username.lower() == 'rusolnik':
                return True
            
            # Проверяем активную подписку
            subscription = self.get_active_subscription(telegram_id)
            if subscription:
                return True
            
            # Проверяем пробный период (тоже считается активной подпиской)
            if self.is_trial_active(telegram_id):
                return True
            
            return False
        except Exception as e:
            print(f"Ошибка при проверке подписки: {e}")
            return False
    
    def is_user_subscribed(self, telegram_id: int, username: Optional[str] = None) -> bool:
        """Проверить подписку (алиас для has_active_subscription)"""
        return self.has_active_subscription(telegram_id, username)
    
    def activate_referral_reward(self, new_user_id: int, referrer_id: int) -> bool:
        """Активировать награду за referral: 3 дня подписки новому пользователю"""
        try:
            from datetime import datetime, timezone, timedelta
            
            now = datetime.now(timezone.utc)
            end_date = now + timedelta(days=3)
            
            # Используем допустимый subscription_type (1_month) но с кастомной датой окончания (3 дня)
            # Добавляем пометку в payment_charge_id что это referral награда
            subscription_data = {
                'user_id': new_user_id,
                'subscription_type': '1_month',  # Используем допустимый тип для CHECK constraint
                'start_date': now.isoformat(),
                'end_date': end_date.isoformat(),  # Всего 3 дня вместо месяца
                'is_active': True,
                'auto_renew': False,
                'payment_charge_id': f'referral_reward_{referrer_id}'  # Помечаем как referral награду
            }
            
            response = self.client.table('subscriptions').insert(subscription_data).execute()
            
            if response.data:
                print(f"[Referral] ✅ 3 дня подписки созданы для пользователя {new_user_id} (реферер: {referrer_id})")
                return True
            
            return False
        except Exception as e:
            print(f"Ошибка при активации награды за referral: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_referral_code(self, telegram_id: int) -> Optional[str]:
        """Получить referral код пользователя"""
        try:
            user = self.get_user(telegram_id)
            if user:
                return user.get('referral_code') or f"ref_{telegram_id}"
            return f"ref_{telegram_id}"
        except Exception as e:
            print(f"Ошибка при получении referral кода: {e}")
            return f"ref_{telegram_id}"
    
    # Методы для работы с пробным периодом
    def activate_trial(self, telegram_id: int) -> bool:
        """Активировать пробный период для пользователя (24 часа)"""
        try:
            from datetime import datetime, timezone
            
            user = self.get_user(telegram_id)
            if not user:
                # Если пользователя нет, создаем (нужно будет назначить ключ отдельно)
                # Но для пробного периода нужно сначала создать пользователя
                return False
            
            # Проверяем, не использован ли уже пробный период
            if user.get('trial_used', False):
                return False
            
            # Активируем пробный период
            now = datetime.now(timezone.utc)
            self.client.table('users').update({
                'trial_start': now.isoformat(),
                'trial_used': True
            }).eq('telegram_id', telegram_id).execute()
            
            print(f"[Trial] ✅ Пробный период активирован для пользователя {telegram_id}")
            return True
        except Exception as e:
            print(f"Ошибка при активации пробного периода: {e}")
            return False
    
    def is_trial_active(self, telegram_id: int) -> bool:
        """Проверить, активен ли пробный период для пользователя"""
        try:
            user = self.get_user(telegram_id)
            if not user:
                return False
            
            trial_start = user.get('trial_start')
            if not trial_start:
                return False
            
            # Используем функцию из БД или проверяем вручную
            from datetime import datetime, timezone, timedelta
            import dateutil.parser
            
            try:
                # Парсим дату из строки
                if isinstance(trial_start, str):
                    trial_start_dt = dateutil.parser.parse(trial_start)
                else:
                    trial_start_dt = trial_start
                
                # Проверяем, что прошло менее 24 часов
                now = datetime.now(timezone.utc)
                if isinstance(trial_start_dt, str):
                    trial_start_dt = dateutil.parser.parse(trial_start_dt)
                
                # Если trial_start_dt не в UTC, конвертируем
                if trial_start_dt.tzinfo is None:
                    trial_start_dt = trial_start_dt.replace(tzinfo=timezone.utc)
                
                time_diff = now - trial_start_dt
                is_active = time_diff < timedelta(hours=24)
                
                return is_active
            except Exception as parse_error:
                print(f"Ошибка при парсинге даты пробного периода: {parse_error}")
                return False
            
        except Exception as e:
            print(f"Ошибка при проверке пробного периода: {e}")
            return False
    
    def can_use_trial(self, telegram_id: int) -> bool:
        """Проверить, может ли пользователь использовать пробный период"""
        try:
            user = self.get_user(telegram_id)
            if not user:
                # Новый пользователь может использовать пробный период
                return True
            
            # Проверяем, использован ли уже пробный период
            trial_used = user.get('trial_used', False)
            return not trial_used
            
        except Exception as e:
            print(f"Ошибка при проверке возможности пробного периода: {e}")
            return False
    
    def get_trial_status(self, telegram_id: int) -> Dict[str, Any]:
        """Получить статус пробного периода пользователя"""
        try:
            user = self.get_user(telegram_id)
            if not user:
                return {
                    'can_use': True,
                    'is_active': False,
                    'trial_used': False,
                    'trial_start': None,
                    'hours_remaining': None
                }
            
            trial_start = user.get('trial_start')
            trial_used = user.get('trial_used', False)
            is_active = self.is_trial_active(telegram_id)
            
            hours_remaining = None
            if is_active and trial_start:
                from datetime import datetime, timezone, timedelta
                import dateutil.parser
                
                try:
                    if isinstance(trial_start, str):
                        trial_start_dt = dateutil.parser.parse(trial_start)
                    else:
                        trial_start_dt = trial_start
                    
                    if trial_start_dt.tzinfo is None:
                        trial_start_dt = trial_start_dt.replace(tzinfo=timezone.utc)
                    
                    now = datetime.now(timezone.utc)
                    time_diff = now - trial_start_dt
                    hours_remaining = max(0, 24 - (time_diff.total_seconds() / 3600))
                    hours_remaining = round(hours_remaining, 2)
                except Exception:
                    pass
            
            return {
                'can_use': not trial_used,
                'is_active': is_active,
                'trial_used': trial_used,
                'trial_start': trial_start,
                'hours_remaining': hours_remaining
            }
            
        except Exception as e:
            print(f"Ошибка при получении статуса пробного периода: {e}")
            return {
                'can_use': False,
                'is_active': False,
                'trial_used': False,
                'trial_start': None,
                'hours_remaining': None
            }
    
    # Методы для статистики админки
    def get_all_users_count(self) -> int:
        """Получить общее количество пользователей"""
        try:
            response = self.client.table('users').select('telegram_id', count='exact').execute()
            return response.count if hasattr(response, 'count') else len(response.data) if response.data else 0
        except Exception as e:
            print(f"Ошибка при получении количества пользователей: {e}")
            return 0
    
    def get_active_keys_count(self) -> int:
        """Получить количество активных API ключей"""
        try:
            response = self.client.table('api_keys').select('key_id', count='exact').eq('is_active', True).execute()
            return response.count if hasattr(response, 'count') else len(response.data) if response.data else 0
        except Exception as e:
            print(f"Ошибка при получении количества активных ключей: {e}")
            return 0
    
    def get_active_trials_count(self) -> int:
        """Получить количество активных пробных периодов"""
        try:
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            cutoff = (now - timedelta(hours=24)).isoformat()
            
            response = self.client.table('users').select('telegram_id', count='exact').eq('trial_used', True).gte('trial_start', cutoff).execute()
            return response.count if hasattr(response, 'count') else len(response.data) if response.data else 0
        except Exception as e:
            print(f"Ошибка при получении количества активных пробных периодов: {e}")
            return 0
    
    def get_subscribed_users_count(self) -> int:
        """Получить количество пользователей с активной подпиской"""
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            
            response = self.client.table('subscriptions').select('user_id', count='exact').eq('is_active', True).gte('end_date', now.isoformat()).execute()
            # Получаем уникальных пользователей
            if response.data:
                unique_users = set(sub.get('user_id') for sub in response.data)
                return len(unique_users)
            return response.count if hasattr(response, 'count') else 0
        except Exception as e:
            print(f"Ошибка при получении количества подписанных пользователей: {e}")
            return 0
    
    def get_all_users_list(self, limit: int = 1000, offset: int = 0) -> List[Dict]:
        """Получить список всех пользователей с ID и username"""
        try:
            response = self.client.table('users').select('telegram_id, username, first_name, trial_start, trial_used').order('telegram_id', desc=False).range(offset, offset + limit - 1).execute()
            return response.data if response.data else []
        except Exception as e:
            print(f"Ошибка при получении списка пользователей: {e}")
            return []
    
    def search_user_by_id_or_username(self, search_term: str) -> Optional[Dict]:
        """Поиск пользователя по ID или username"""
        try:
            # Пробуем найти по telegram_id
            try:
                telegram_id = int(search_term)
                user = self.get_user(telegram_id)
                if user:
                    return user
            except ValueError:
                pass
            
            # Пробуем найти по username (без @)
            username = search_term.lstrip('@')
            response = self.client.table('users').select('*').eq('username', username).limit(1).execute()
            if response.data:
                return response.data[0]
            
            return None
        except Exception as e:
            print(f"Ошибка при поиске пользователя: {e}")
            return None

