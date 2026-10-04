import http.server
import socketserver
import os

# Простой файловый сервер для раздачи фотографий пользователей
# по публичным URL, чтобы их мог скачать OpenRouter (GPT Image) для переноса лица.
PORT = int(os.getenv("PHOTO_SERVER_PORT", "8000"))
DIRECTORY = "/app/photos"

os.makedirs(DIRECTORY, exist_ok=True)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def log_message(self, format, *args):
        print(f"[photos] {self.command} {self.path}")


if __name__ == "__main__":
    print(f"Photo server serving {DIRECTORY} on 0.0.0.0:{PORT}")
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        httpd.serve_forever()