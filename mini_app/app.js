// Инициализация Telegram WebApp
const tg = window.Telegram?.WebApp;
if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor('#81D4FA'); // Небесно-голубой цвет заголовка
    tg.setBackgroundColor('#F5F5F0'); // Цвет фона
}

// Функция для открытия профиля пользователя в Telegram
function openTelegramUser(event, username) {
    event.preventDefault();
    
    // Если мы в Mini App внутри Telegram
    if (tg) {
        // Используем https:// ссылку через openLink - это перекинет в Telegram
        const url = `https://t.me/${username}`;
        tg.openLink(url);
    } else {
        // Если открыто в браузере, используем обычную ссылку
        const url = `https://t.me/${username}`;
        window.open(url, '_blank');
    }
    
    return false;
}

// Простая страница "О проекте" - нет сложной логики
document.addEventListener('DOMContentLoaded', () => {
    console.log('✅ Страница "О проекте" загружена');
    
    // Если есть данные пользователя из Telegram, можно их использовать
    if (tg?.initDataUnsafe?.user) {
        const user = tg.initDataUnsafe.user;
        console.log('Пользователь:', user.first_name || user.username);
    }
});
