// Конфигурация Supabase
// Значения по умолчанию из .env (для ручной настройки)
const DEFAULT_SUPABASE_URL = 'https://pyrkntwervbrursneynd.supabase.co';
const DEFAULT_SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB5cmtudHdlcnZicnVyc25leW5kIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE5MzI1NDksImV4cCI6MjA3NzUwODU0OX0.D1pSh-60JmROW6zh7g_kjnH1tDuYxWOC0DiSfo3oR4o'; // Anon public key (JWT токен)

// Пытаемся получить из URL параметров, затем из localStorage, затем используем значения по умолчанию
function getSupabaseConfig() {
    // 1. Пытаемся получить из URL параметров (передается ботом)
    const urlParams = new URLSearchParams(window.location.search);
    let supabaseUrl = urlParams.get('supabase_url');
    let supabaseKey = urlParams.get('supabase_key');
    
    // Декодируем если были закодированы
    if (supabaseUrl) {
        supabaseUrl = decodeURIComponent(supabaseUrl);
    }
    if (supabaseKey) {
        supabaseKey = decodeURIComponent(supabaseKey);
    }
    
    console.log('🔍 Получение конфигурации Supabase:');
    console.log('  URL из параметров:', supabaseUrl ? (supabaseUrl.substring(0, 40) + '...') : 'NULL');
    console.log('  Key из параметров:', supabaseKey ? 'SET (' + supabaseKey.length + ' символов)' : 'NULL');
    
    // 2. Если не переданы через URL, пытаемся получить из localStorage
    if (!supabaseUrl || !supabaseKey) {
        const stored = localStorage.getItem('supabase_config');
        if (stored) {
            try {
                const config = JSON.parse(stored);
                if (config.url && !supabaseUrl) {
                    supabaseUrl = config.url;
                    console.log('  ✅ URL найден в localStorage');
                }
                if (config.key && !supabaseKey) {
                    supabaseKey = config.key;
                    console.log('  ✅ Key найден в localStorage');
                }
            } catch (e) {
                console.error('❌ Ошибка чтения конфигурации из localStorage:', e);
            }
        }
    }
    
    // Проверяем и исправляем формат URL
    if (supabaseUrl) {
        // Убираем пробелы и лишние символы
        supabaseUrl = supabaseUrl.trim();
        
        // Добавляем протокол если отсутствует
        if (!supabaseUrl.startsWith('http://') && !supabaseUrl.startsWith('https://')) {
            console.warn('⚠️ SUPABASE_URL не содержит протокол, добавляю https://');
            supabaseUrl = 'https://' + supabaseUrl;
        }
        
        // Убираем слеш в конце URL если есть
        if (supabaseUrl.endsWith('/')) {
            supabaseUrl = supabaseUrl.slice(0, -1);
        }
    }
    
    // 3. Сохраняем в localStorage для следующих раз
    if (supabaseUrl && supabaseKey) {
        localStorage.setItem('supabase_config', JSON.stringify({
            url: supabaseUrl,
            key: supabaseKey
        }));
        console.log('✅ Конфигурация сохранена в localStorage');
    }
    
    // 4. Используем значения по умолчанию если ничего не найдено
    if (!supabaseUrl || !supabaseKey || supabaseUrl.includes('YOUR_SUPABASE_URL')) {
        console.log('⚠️ Параметры не найдены, используем значения по умолчанию из .env');
        supabaseUrl = supabaseUrl && !supabaseUrl.includes('YOUR_SUPABASE_URL') ? supabaseUrl : DEFAULT_SUPABASE_URL;
        supabaseKey = supabaseKey && !supabaseKey.includes('YOUR_SUPABASE_ANON_KEY') ? supabaseKey : DEFAULT_SUPABASE_KEY;
        console.log('✅ Используются значения по умолчанию');
    }
    
    return { url: supabaseUrl, key: supabaseKey };
}

const { url: SUPABASE_URL, key: SUPABASE_ANON_KEY } = getSupabaseConfig();

// Инициализация Telegram WebApp
const tg = window.Telegram?.WebApp;
if (tg) {
    tg.ready();
    tg.expand();
}

// Инициализация Supabase
// Используем такую же простую инициализацию, как в Python боте (database.py)
let supabase = null;
try {
    if (!SUPABASE_URL || !SUPABASE_ANON_KEY || 
        SUPABASE_URL.includes('YOUR_SUPABASE_URL') || 
        SUPABASE_ANON_KEY.includes('YOUR_SUPABASE_ANON_KEY')) {
        console.warn('⚠️ Supabase параметры не настроены, клиент не будет инициализирован');
    } else {
        // Простая инициализация без дополнительных параметров (как в database.py)
        supabase = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
        console.log('✅ Supabase клиент инициализирован (простая инициализация)');
        console.log('📡 URL:', SUPABASE_URL.substring(0, 40) + '...');
        console.log('🔑 Key:', SUPABASE_ANON_KEY.substring(0, 20) + '... (длина: ' + SUPABASE_ANON_KEY.length + ')');
    }
} catch (error) {
    console.error('❌ Ошибка инициализации Supabase клиента:', error);
    console.error('📋 Детали ошибки:', {
        message: error.message,
        stack: error.stack
    });
}

// Глобальные переменные
let currentUserId = null;
let chats = [];
let currentChatId = null;
let deleteChatId = null;

// Инициализация приложения
document.addEventListener('DOMContentLoaded', async () => {
    try {
        console.log('🔍 Начинаю инициализацию Mini App...');
        console.log('📍 URL параметры:', window.location.search);
        console.log('🔑 SUPABASE_URL:', SUPABASE_URL ? (SUPABASE_URL.substring(0, 30) + '...') : 'NULL');
        console.log('🔑 SUPABASE_ANON_KEY:', SUPABASE_ANON_KEY ? (SUPABASE_ANON_KEY.substring(0, 20) + '...') : 'NULL');
        
        // Проверяем конфигурацию Supabase
        if (!SUPABASE_URL || !SUPABASE_ANON_KEY || 
            SUPABASE_URL.includes('YOUR_SUPABASE_URL') || 
            SUPABASE_ANON_KEY.includes('YOUR_SUPABASE_ANON_KEY')) {
            const errorMsg = 'Supabase не настроен. Пожалуйста, настройте SUPABASE_URL и SUPABASE_ANON_KEY.';
            console.error('❌', errorMsg);
            console.error('📋 Текущие значения:');
            console.error('  URL:', SUPABASE_URL);
            console.error('  Key:', SUPABASE_ANON_KEY ? 'SET' : 'MISSING');
            showError(errorMsg);
            return;
        }
        
        console.log('✅ Supabase конфигурация найдена');
        
        // Проверяем что Supabase клиент инициализирован
        if (!supabase) {
            throw new Error('Supabase клиент не инициализирован. Проверьте параметры SUPABASE_URL и SUPABASE_ANON_KEY.');
        }
        
        // Получаем данные пользователя из Telegram
        const initData = tg?.initDataUnsafe;
        if (initData && initData.user) {
            currentUserId = initData.user.id;
            // Устанавливаем имя пользователя
            const userName = initData.user.first_name || initData.user.username || 'Пользователь';
            const userNameEl = document.getElementById('userName');
            if (userNameEl) userNameEl.textContent = userName;
            // Устанавливаем инициалы для аватара
            const initials = userName.charAt(0).toUpperCase();
            const userInitialsEl = document.getElementById('userInitials');
            if (userInitialsEl) userInitialsEl.textContent = initials;
            
            // Загружаем чаты
            await loadChats();
        } else {
            // Для тестирования без Telegram можно использовать тестовый ID
            if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
                console.warn('Telegram WebApp data not available. Using test mode.');
                currentUserId = parseInt(localStorage.getItem('test_user_id') || '1');
                const userNameEl = document.getElementById('userName');
                if (userNameEl) userNameEl.textContent = 'Тестовый пользователь';
                await loadChats();
            } else {
                showError('Не удалось получить данные пользователя из Telegram');
            }
        }
    } catch (error) {
        console.error('Ошибка инициализации:', error);
        showError('Ошибка при загрузке данных: ' + error.message);
    }
});


// Загрузка списка чатов
// Точная копия логики из database.py get_user_chats()
async function loadChats() {
    try {
        showLoading();
        
        if (!currentUserId) {
            throw new Error('User ID не установлен');
        }
        
        if (!supabase) {
            throw new Error('Supabase клиент не инициализирован');
        }
        
        // Python: response = self.client.table('chats').select('*').eq('user_id', telegram_id).order('created_at', desc=False).execute()
        // JS версия (один в один):
        console.log('📤 Запрос к Supabase:');
        console.log('  Таблица: chats');
        console.log('  user_id:', currentUserId);
        console.log('  URL:', SUPABASE_URL);
        console.log('  Key (первые 20 символов):', SUPABASE_ANON_KEY.substring(0, 20));
        
        const response = await supabase
            .from('chats')
            .select('*')
            .eq('user_id', currentUserId)
            .order('created_at', { ascending: false }); // Последние первыми для отображения
        
        console.log('📥 Ответ от Supabase:');
        console.log('  Error:', response.error ? JSON.stringify(response.error, null, 2) : 'Нет');
        console.log('  Data:', response.data ? `${response.data.length} записей` : 'NULL');
        
        // Python: return response.data if response.data else []
        // JS версия (один в один):
        if (response.error) {
            console.error('❌ Ошибка при получении чатов:', response.error);
            console.error('📋 Детали ошибки:');
            console.error('  Код:', response.error.code);
            console.error('  Сообщение:', response.error.message);
            console.error('  Детали:', response.error.details);
            console.error('  Подсказка:', response.error.hint);
            
            // Если это CORS или сеть
            if (response.error.message && response.error.message.includes('fetch')) {
                console.error('⚠️ Проблема с сетью или CORS!');
                console.error('📝 Проверьте:');
                console.error('  1. Выполнена ли SQL миграция 004_disable_rls.sql в Supabase Dashboard?');
                console.error('  2. Настроен ли CORS в Supabase Dashboard → Settings → API?');
                console.error('  3. Доступен ли Supabase сервер?');
            }
            
            chats = [];
            throw new Error(`Ошибка Supabase: ${response.error.message || JSON.stringify(response.error)}`);
        } else {
            chats = response.data || [];
            console.log('✅ Загружено чатов:', chats.length);
            if (chats.length > 0) {
                console.log('📋 Первый чат:', chats[0]);
            }
        }
        
        // Получаем активный чат (последний созданный или сохраненный в localStorage)
        const savedActiveChatId = localStorage.getItem('activeChatId');
        if (savedActiveChatId && chats.find(c => c.chat_id === savedActiveChatId)) {
            currentChatId = savedActiveChatId;
        } else if (chats.length > 0) {
            currentChatId = chats[0].chat_id;
        }
        
        renderChats();
        
    } catch (error) {
        console.error('Ошибка при получении чатов:', error);
        chats = [];
        showError(`Не удалось загрузить диалоги: ${error.message}`);
    }
}

// Отображение списка чатов
function renderChats() {
    hideLoading();
    
    const floatingBtn = document.getElementById('floatingNewChatBtn');
    
    if (chats.length === 0) {
        document.getElementById('emptyState').style.display = 'block';
        document.getElementById('chatsList').style.display = 'none';
        if (floatingBtn) floatingBtn.style.display = 'none';
        return;
    }
    
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('chatsList').style.display = 'block';
    if (floatingBtn) floatingBtn.style.display = 'flex';
    
    const chatsList = document.getElementById('chatsList');
    chatsList.innerHTML = '';
    
    chats.forEach((chat, index) => {
        const chatElement = createChatElement(chat);
        chatElement.style.animationDelay = `${index * 0.05}s`;
        chatsList.appendChild(chatElement);
    });
}

// Создание элемента чата
function createChatElement(chat) {
    const div = document.createElement('div');
    div.className = `chat-item ${chat.chat_id === currentChatId ? 'active' : ''}`;
    div.onclick = () => switchChat(chat.chat_id);
    
    const chatInfo = document.createElement('div');
    chatInfo.className = 'chat-info';
    
    const title = document.createElement('div');
    title.className = 'chat-title';
    title.textContent = chat.title;
    
    const meta = document.createElement('div');
    meta.className = 'chat-meta';
    meta.textContent = formatDate(chat.created_at);
    
    chatInfo.appendChild(title);
    chatInfo.appendChild(meta);
    
    const actions = document.createElement('div');
    actions.className = 'chat-actions';
    
    const renameBtn = document.createElement('button');
    renameBtn.className = 'btn-icon';
    renameBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
    </svg>`;
    renameBtn.onclick = (e) => {
        e.stopPropagation();
        openRenameModal(chat);
    };
    
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'btn-icon delete-btn';
    deleteBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="3 6 5 6 21 6"></polyline>
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
    </svg>`;
    deleteBtn.onclick = (e) => {
        e.stopPropagation();
        openDeleteModal(chat.chat_id);
    };
    
    actions.appendChild(deleteBtn);
    
    div.appendChild(chatInfo);
    div.appendChild(actions);
    
    return div;
}

// Переключение активного чата
async function switchChat(chatId) {
    if (currentChatId === chatId) return;
    
    currentChatId = chatId;
    localStorage.setItem('activeChatId', chatId);
    
    // Обновляем UI
    renderChats();
    
    // Закрываем Mini App и возвращаемся в бота
    if (tg) {
        tg.close();
    }
}

// Создание нового чата
function createNewChat() {
    if (!currentUserId) {
        alert('Пользователь не определен. Попробуйте перезагрузить страницу.');
        return;
    }
    
    const modalTitle = document.getElementById('modalTitle');
    const chatInput = document.getElementById('chatTitleInput');
    const submitBtn = document.getElementById('modalSubmitBtn');
    const modal = document.getElementById('modal');
    
    if (modalTitle) modalTitle.textContent = 'Новый чат';
    if (chatInput) chatInput.value = '';
    if (submitBtn) submitBtn.textContent = 'Создать';
    if (modal) {
        modal.style.display = 'flex';
        setTimeout(() => {
            if (chatInput) chatInput.focus();
        }, 100);
    }
}

// Закрытие модального окна
function closeModal() {
    document.getElementById('modal').style.display = 'none';
    document.getElementById('chatTitleInput').value = '';
}

// Отправка формы модального окна - создание чата
// Точная копия логики из database.py create_chat()
async function submitModal() {
    const title = document.getElementById('chatTitleInput').value.trim();
    
    if (!title) {
        alert('Введите название чата');
        return;
    }
    
    if (!currentUserId || !supabase) {
        alert('Ошибка: пользователь не определен');
        return;
    }
    
    try {
        console.log('📤 Создание чата:');
        console.log('  user_id:', currentUserId);
        console.log('  title:', title);
        console.log('  URL:', SUPABASE_URL);
        
        // Python: response = self.client.table('chats').insert(data).execute()
        // Python: return response.data[0] if response.data else None
        const response = await supabase
            .from('chats')
            .insert({
                user_id: currentUserId,
                title: title
            })
            .select();
        
        console.log('📥 Ответ от Supabase:');
        console.log('  Error:', response.error ? JSON.stringify(response.error, null, 2) : 'Нет');
        console.log('  Data:', response.data ? `${response.data.length} записей` : 'NULL');
        
        if (response.error) {
            console.error('❌ Ошибка при создании чата:', response.error);
            console.error('📋 Детали ошибки:');
            console.error('  Код:', response.error.code);
            console.error('  Сообщение:', response.error.message);
            console.error('  Детали:', response.error.details);
            console.error('  Подсказка:', response.error.hint);
            
            // Если это CORS или сеть
            if (response.error.message && (response.error.message.includes('fetch') || response.error.message.includes('Failed'))) {
                console.error('⚠️ Проблема с сетью или CORS!');
                console.error('📝 Проверьте:');
                console.error('  1. Выполнена ли SQL миграция 004_disable_rls.sql в Supabase Dashboard?');
                console.error('  2. Настроен ли CORS в Supabase Dashboard → Settings → API?');
                console.error('  3. Доступен ли Supabase сервер?');
            }
            
            throw response.error;
        }
        
        // Python: return response.data[0] if response.data else None
        if (response.data && response.data.length > 0) {
            const newChat = response.data[0];
            console.log('✅ Чат создан:', newChat);
            chats.unshift(newChat);
            currentChatId = newChat.chat_id;
            localStorage.setItem('activeChatId', currentChatId);
            renderChats();
            closeModal();
        } else {
            throw new Error('Чат не был создан - ответ пустой');
        }
        
    } catch (error) {
        console.error('❌ Критическая ошибка при создании чата:', error);
        console.error('📋 Тип ошибки:', error.constructor.name);
        console.error('📋 Сообщение:', error.message);
        console.error('📋 Stack:', error.stack);
        
        let errorMsg = 'Не удалось создать чат';
        if (error.message && error.message.includes('fetch')) {
            errorMsg += '. Проблема с подключением к серверу. Проверьте настройки CORS и RLS в Supabase Dashboard.';
        } else {
            errorMsg += ': ' + (error.message || JSON.stringify(error));
        }
        
        alert(errorMsg);
    }
}

// Открытие модального окна удаления
function openDeleteModal(chatId) {
    deleteChatId = chatId;
    document.getElementById('deleteModal').style.display = 'flex';
}

// Закрытие модального окна удаления
function closeDeleteModal() {
    document.getElementById('deleteModal').style.display = 'none';
    deleteChatId = null;
}

// Подтверждение удаления
async function confirmDelete() {
    if (!deleteChatId) return;
    
    try {
        const { error } = await supabase
            .from('chats')
            .delete()
            .eq('chat_id', deleteChatId);
        
        if (error) throw error;
        
        // Удаляем из локального массива
        chats = chats.filter(c => c.chat_id !== deleteChatId);
        
        // Если удалили активный чат, выбираем другой
        if (currentChatId === deleteChatId) {
            if (chats.length > 0) {
                currentChatId = chats[0].chat_id;
                localStorage.setItem('activeChatId', currentChatId);
            } else {
                currentChatId = null;
                localStorage.removeItem('activeChatId');
            }
        }
        
        closeDeleteModal();
        renderChats();
        
    } catch (error) {
        console.error('Ошибка удаления:', error);
        alert('Не удалось удалить чат: ' + error.message);
    }
}

// Вспомогательные функции
function showLoading() {
    document.getElementById('loading').style.display = 'flex';
    document.getElementById('chatsList').style.display = 'none';
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('error').style.display = 'none';
}

function hideLoading() {
    document.getElementById('loading').style.display = 'none';
}

function showError(message) {
    document.getElementById('loading').style.display = 'none';
    document.getElementById('error').style.display = 'block';
    document.getElementById('error').querySelector('p').textContent = message;
    document.getElementById('chatsList').style.display = 'none';
    document.getElementById('emptyState').style.display = 'none';
}

function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;
    
    if (diff < 60000) return 'Только что';
    if (diff < 3600000) return `${Math.floor(diff / 60000)} мин назад`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)} ч назад`;
    if (diff < 604800000) return `${Math.floor(diff / 86400000)} дн назад`;
    
    return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
}

// Обработка Enter в поле ввода
document.getElementById('chatTitleInput')?.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        submitModal();
    }
});

// Обработчик кнопки нового чата
document.getElementById('newChatBtn')?.addEventListener('click', createNewChat);
