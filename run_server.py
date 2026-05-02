from waitress import serve
from core.wsgi import application

print("Starting server at http://127.0.0.1:8000 Nginx will do the rest.")
serve(application, host="127.0.0.1", port=8000)
