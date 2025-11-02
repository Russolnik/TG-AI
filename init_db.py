"""
Скрипт для инициализации базы данных и добавления API-ключей
Использование: python init_db.py
"""
import config
from database import Database

def main():
    print("Инициализация базы данных...")
    
    db = Database()
    
    # Проверяем существующие ключи
    existing_keys = db.get_all_api_keys()
    existing_key_values = {key['api_key'] for key in existing_keys}
    
    print(f"Найдено {len(existing_keys)} ключей в базе данных")
    
    # Добавляем ключи из конфига, которых нет в БД
    new_keys_count = 0
    for api_key in config.GEMINI_API_KEYS:
        if api_key not in existing_key_values:
            try:
                db.client.table('api_keys').insert({
                    'api_key': api_key,
                    'is_active': True
                }).execute()
                new_keys_count += 1
                print(f"✓ Добавлен новый API-ключ")
            except Exception as e:
                print(f"✗ Ошибка при добавлении ключа: {e}")
    
    print(f"\nДобавлено новых ключей: {new_keys_count}")
    print(f"Всего ключей в базе: {len(existing_keys) + new_keys_count}")
    
    # Показываем статистику
    all_keys = db.get_all_api_keys()
    active_keys = [k for k in all_keys if k.get('is_active')]
    print(f"Активных ключей: {len(active_keys)}")
    
    print("\n✓ Инициализация завершена!")

if __name__ == '__main__':
    main()

