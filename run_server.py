# from waitress import serve
# from core.wsgi import application

# print("Starting server at http://127.0.0.1:8000 Nginx will do the rest.")
# serve(application, host="127.0.0.1", port=8000)


import logging

from waitress import serve

from core.wsgi import application

# Suppress noisy queue warnings (optional)
logging.getLogger("waitress.queue").setLevel(logging.ERROR)

print("Starting server at http://127.0.0.1:8000 - Stay awake lol.")

serve(
    application,
    host="127.0.0.1",
    port=8000,
    # Windows-specific tuning
    threads=50,  # Increase from default 4 (Windows handles threads well)
    # connection_limit=250,  # Max concurrent connections
    backlog=2048,  # OS TCP queue size (Windows default may be lower)
    # Performance tweaks for Windows
    # channel_request_lookahead=10,  # Read ahead while processing
    expose_tracebacks=False,  # Security: hide tracebacks in production
    # If behind Nginx (which you are)
    # url_scheme="http",  # Or 'https' if Nginx terminates SSL
    # url_prefix="",  # Set if Nginx uses subpath like /myapp/
)
