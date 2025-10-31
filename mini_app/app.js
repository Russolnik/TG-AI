// Конфигурация Supabase (замените на ваши значения)
const SUPABASE_URL = window.location.hostname === 'localhost' 
    ? 'YOUR_SUPABASE_URL' 
    : 'YOUR_SUPABASE_URL';
const SUPABASE_ANON_KEY = window.location.hostname === 'localhost'
    ? 'YOUR_SUPABASE_ANON_KEY'
    : 'YOUR_SUPABASE_ANON_KEY';

// Инициализация Telegram WebApp
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

// Инициализация Supabase
const supabase = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// Глобальные переменные
let currentUserId = null;
let chats = [];
let currentChatId = null;
let deleteChatId = null;
let modalMode = 'create'; // 'create' или 'rename'

// Инициализация приложения
document.addEventListener('DOMContentLoaded', async () => {
    try {
        // Получаем данные пользователя из Telegram
        const initData = tg.initDataUnsafe;
        if (initData && initData.user) {
            currentUserId = initData.user.id;
            await loadChats();
        } else {
            showError('Не удалось получить данные пользователя');
        }
    } catch (error) {
        console.error('Ошибка инициализации:', error);
        showError('Ошибка при загрузке данных');
    }
});

// Загрузка списка чатов
async function loadChats() {
    try {
        showLoading();
        
        // Получаем чаты пользователя из Supabase
        const { data, error } = await supabase
            .from('chats')
            .select('*')
            .eq('user_id', currentUserId)
            .order('created_at', { ascending: false });
        
        if (error) throw error;
        
        chats = data || [];
        
        // Получаем активный чат (последний созданный или сохраненный в localStorage)
        const savedActiveChatId = localStorage.getItem('activeChatId');
        if (savedActiveChatId && chats.find(c => c.chat_id === savedActiveChatId)) {
            currentChatId = savedActiveChatId;
        } else if (chats.length > 0) {
            currentChatId = chats[0].chat_id;
        }
        
        renderChats();
        
    } catch (error) {
        console.error('Ошибка загрузки чатов:', error);
        showError('Не удалось загрузить диалоги');
    }
}

// Отображение списка чатов
function renderChats() {
    hideLoading();
    
    if (chats.length === 0) {
        document.getElementById('emptyState').style.display = 'block';
        document.getElementById('chatsList').style.display = 'none';
        return;
    }
    
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('chatsList').style.display = 'block';
    
    const chatsList = document.getElementById('chatsList');
    chatsList.innerHTML = '';
    
    chats.forEach(chat => {
        const chatElement = createChatElement(chat);
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
    deleteBtn.className = 'btn-icon';
    deleteBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="3 6 5 6 21 6"></polyline>
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
    </svg>`;
    deleteBtn.onclick = (e) => {
        e.stopPropagation();
        openDeleteModal(chat.chat_id);
    };
    
    actions.appendChild(renameBtn);
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
    tg.close();
}

// Создание нового чата
async function createNewChat() {
    modalMode = 'create';
    document.getElementById('modalTitle').textContent = 'Новый чат';
    document.getElementById('chatTitleInput').value = '';
    document.getElementById('modalSubmitBtn').textContent = 'Создать';
    document.getElementById('modal').style.display = 'flex';
    document.getElementById('chatTitleInput').focus();
}

// Открытие модального окна переименования
function openRenameModal(chat) {
    modalMode = 'rename';
    currentChatId = chat.chat_id;
    document.getElementById('modalTitle').textContent = 'Переименовать чат';
    document.getElementById('chatTitleInput').value = chat.title;
    document.getElementById('modalSubmitBtn').textContent = 'Сохранить';
    document.getElementById('modal').style.display = 'flex';
    document.getElementById('chatTitleInput').focus();
}

// Закрытие модального окна
function closeModal() {
    document.getElementById('modal').style.display = 'none';
}

// Отправка формы модального окна
async function submitModal() {
    const title = document.getElementById('chatTitleInput').value.trim();
    
    if (!title) {
        alert('Введите название чата');
        return;
    }
    
    try {
        if (modalMode === 'create') {
            // Создаем новый чат
            const { data, error } = await supabase
                .from('chats')
                .insert({
                    user_id: currentUserId,
                    title: title
                })
                .select()
                .single();
            
            if (error) throw error;
            
            chats.unshift(data);
            currentChatId = data.chat_id;
            localStorage.setItem('activeChatId', currentChatId);
            
        } else {
            // Переименовываем чат
            const { error } = await supabase
                .from('chats')
                .update({ title: title })
                .eq('chat_id', currentChatId);
            
            if (error) throw error;
            
            const chat = chats.find(c => c.chat_id === currentChatId);
            if (chat) {
                chat.title = title;
            }
        }
        
        closeModal();
        renderChats();
        
    } catch (error) {
        console.error('Ошибка сохранения:', error);
        alert('Не удалось сохранить изменения');
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
        alert('Не удалось удалить чат');
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

