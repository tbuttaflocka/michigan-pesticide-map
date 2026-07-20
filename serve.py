#!/usr/bin/env python3
"""Production server entry point using the Waitress WSGI server.

`python app.py` runs Flask's built-in *development* server, which is single-
threaded and not meant to face the public internet. For a public/shared
deployment, run this instead:

    pip install -r requirements.txt   # includes Waitress
    python serve.py                   # serves on HOST:PORT (default 127.0.0.1:8080)

Behind a reverse proxy (nginx/Caddy/IIS) that terminates HTTPS, bind to
localhost and let the proxy handle TLS + the public port:

    HOST=127.0.0.1 PORT=8080 python serve.py

The Flask app object lives in app.py, but `import app` resolves to the app/
*package* (it shadows app.py), so we load app.py explicitly and hand its `app`
object to Waitress. The module-level `application` is also usable as a WSGI
target, e.g.  waitress-serve --listen=127.0.0.1:8080 serve:application
"""
import importlib.util
import os
from pathlib import Path

from waitress import serve

_spec = importlib.util.spec_from_file_location(
    "_pesticide_app", Path(__file__).with_name("app.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
application = _mod.app          # WSGI callable

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    print(f" * Waitress serving Michigan Pesticide Map on http://{host}:{port}")
    serve(application, host=host, port=port, threads=8)
