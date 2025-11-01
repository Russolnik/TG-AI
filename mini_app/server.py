"""
Простой HTTP сервер для локальной разработки Mini App
Запуск: python server.py
Доступ: http://localhost:8000
"""
import http.server
import socketserver
import os
from urllib.parse import urlparse, parse_qs

PORT = 8000
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)
    
    def end_headers(self):
        # Добавляем CORS заголовки для работы с Telegram
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

if __name__ == '__main__':
    os.chdir(DIRECTORY)
    
    with socketserver.TCPServer(("", PORT), MyHTTPRequestHandler) as httpd:
        print(f"🚀 Mini App сервер запущен на http://localhost:{PORT}")
        print(f"📁 Директория: {DIRECTORY}")
        print(f"💡 Для доступа из Telegram используйте ngrok или аналогичный сервис")
        print(f"   Пример: ngrok http {PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n🛑 Сервер остановлен")

