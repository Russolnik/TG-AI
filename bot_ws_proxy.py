"""
WebSocket прокси endpoint для Flask приложения
Интегрирует gemini_ws_proxy.py в Flask приложение для использования с Live чатом
"""

from flask import Flask
from flask_socketio import SocketIO, emit
import asyncio
import websockets
import json
import logging
from gemini_ws_proxy import proxy_websocket, GEMINI_WS_URL

logger = logging.getLogger(__name__)

# Инициализация SocketIO
socketio = None

def init_socketio(app: Flask):
    """Инициализирует SocketIO для Flask приложения"""
    global socketio
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
    return socketio

@socketio.on('connect', namespace='/api/gemini/ws-proxy')
def handle_connect():
    """Обработчик подключения WebSocket клиента"""
    logger.info("WebSocket клиент подключился")
    emit('connected', {'status': 'connected'})

@socketio.on('message', namespace='/api/gemini/ws-proxy')
def handle_message(data):
    """Обработчик сообщений от WebSocket клиента"""
    try:
        if isinstance(data, str):
            data = json.loads(data)
        
        api_key = data.get('api_key')
        if not api_key:
            emit('error', {'error': 'API key required'})
            return
        
        # Запускаем проксирование в отдельном потоке
        asyncio.run(proxy_websocket_async(data, api_key))
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}", exc_info=True)
        emit('error', {'error': str(e)})

async def proxy_websocket_async(data: dict, api_key: str):
    """Асинхронная функция для проксирования WebSocket"""
    try:
        # Создаем WebSocket соединение к Google API
        google_ws_url = f"{GEMINI_WS_URL}?key={api_key}"
        headers = {"x-goog-api-key": api_key}
        
        async with websockets.connect(google_ws_url, extra_headers=headers) as google_ws:
            # Отправляем первое сообщение к Google
            if 'message' in data:
                await google_ws.send(data['message'])
            
            # Проксируем сообщения в обе стороны
            async def forward_to_google():
                # Слушаем сообщения от клиента через SocketIO
                # Это сложно реализовать, т.к. SocketIO и asyncio плохо работают вместе
                pass
            
            async def forward_to_client():
                async for message in google_ws:
                    # Отправляем сообщение клиенту через SocketIO
                    socketio.emit('message', message, namespace='/api/gemini/ws-proxy')
            
            await asyncio.gather(
                forward_to_client(),
                return_exceptions=True
            )
    except Exception as e:
        logger.error(f"Ошибка проксирования WebSocket: {e}", exc_info=True)

