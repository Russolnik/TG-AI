"""
WebSocket прокси для Google Gemini Live API
Проксирует соединения от клиента к Google API через сервер
Это позволяет обойти блокировки в РФ/Беларуси
"""

import asyncio
import websockets
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# URL WebSocket для Google Gemini Live API
GEMINI_WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService/BidiGenerateContent"

async def proxy_websocket(client_ws, api_key: str):
    """
    Проксирует WebSocket соединение от клиента к Google API
    
    Args:
        client_ws: WebSocket соединение от клиента
        api_key: API ключ Google Gemini
    """
    google_ws = None
    try:
        # Создаем WebSocket соединение к Google API
        headers = {
            "x-goog-api-key": api_key,
        }
        
        google_ws_url = f"{GEMINI_WS_URL}?key={api_key}"
        
        logger.info(f"Подключение к Google API WebSocket...")
        async with websockets.connect(google_ws_url, extra_headers=headers) as google_ws:
            logger.info("Успешно подключено к Google API WebSocket")
            
            # Запускаем две задачи для двунаправленной передачи данных
            async def client_to_google():
                try:
                    async for message in client_ws:
                        # Пересылаем сообщение от клиента к Google
                        await google_ws.send(message)
                        logger.debug(f"Отправлено клиенту->Google: {len(message)} байт")
                except websockets.exceptions.ConnectionClosed:
                    logger.info("Клиент отключился")
                except Exception as e:
                    logger.error(f"Ошибка в client_to_google: {e}", exc_info=True)
            
            async def google_to_client():
                try:
                    async for message in google_ws:
                        # Пересылаем сообщение от Google к клиенту
                        await client_ws.send(message)
                        logger.debug(f"Отправлено Google->клиенту: {len(message)} байт")
                except websockets.exceptions.ConnectionClosed:
                    logger.info("Google API отключился")
                except Exception as e:
                    logger.error(f"Ошибка в google_to_client: {e}", exc_info=True)
            
            # Ждем завершения обеих задач
            await asyncio.gather(
                client_to_google(),
                google_to_client(),
                return_exceptions=True
            )
            
    except Exception as e:
        logger.error(f"Ошибка в proxy_websocket: {e}", exc_info=True)
        try:
            await client_ws.close(code=1011, reason=f"Proxy error: {str(e)}")
        except:
            pass

async def handle_websocket_proxy(websocket, path):
    """
    Обработчик WebSocket соединения от клиента
    """
    try:
        # Получаем API ключ из query параметров или первого сообщения
        query_params = path.split('?')[1] if '?' in path else ''
        api_key = None
        
        if query_params:
            from urllib.parse import parse_qs
            params = parse_qs(query_params)
            api_key = params.get('api_key', [None])[0]
        
        if not api_key:
            # Ждем первое сообщение с API ключом
            first_message = await websocket.recv()
            try:
                data = json.loads(first_message)
                api_key = data.get('api_key')
            except:
                await websocket.close(code=1008, reason="API key required")
                return
        
        logger.info(f"Начало проксирования WebSocket для API ключа: {api_key[:10]}...")
        await proxy_websocket(websocket, api_key)
        
    except websockets.exceptions.ConnectionClosed:
        logger.info("WebSocket соединение закрыто")
    except Exception as e:
        logger.error(f"Ошибка в handle_websocket_proxy: {e}", exc_info=True)

async def start_websocket_proxy(port: int = 8765):
    """
    Запускает WebSocket прокси сервер
    
    Args:
        port: Порт для WebSocket сервера
    """
    logger.info(f"Запуск WebSocket прокси сервера на порту {port}...")
    async with websockets.serve(handle_websocket_proxy, "0.0.0.0", port):
        logger.info(f"WebSocket прокси сервер запущен на ws://0.0.0.0:{port}")
        await asyncio.Future()  # Запускаем бесконечно

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(start_websocket_proxy(port=8765))

