#!/usr/bin/env python3
"""Production server entry point using the Waitress WSGI server.

`python app.py` runs Flask's built-in *development* server, which is single-
threaded and not meant to face the public internet. For a public/shared
deployment, run this instead:

    pip install -r requirements.txt   # includes Waitress
    python serve.py                   # binds 0.0.0.0 on $PORT (default 8080)

It always binds host 0.0.0.0 (all interfaces) so hosting platforms like Render
can reach it, and reads the port from the PORT environment variable that the
platform provides (falling back to 8080 for local use). Locally you can still
open it at http://localhost:<port>. Behind a reverse proxy that terminates
HTTPS, restrict outside access to the app's port at the firewall/proxy layer.

The Flask app object lives in app.py, but `import app` resolves to the app/
*package* (it shadows app.py), so we load app.py explicitly and hand its `app`
object to Waitress. The module-level `application` is also usable as a WSGI
target, e.g.  waitress-serve --listen=0.0.0.0:8080 serve:application
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
    # Bind 0.0.0.0 unconditionally: hosting platforms like Render route traffic
    # to the container's public interface, so the app MUST listen on all
    # interfaces (not 127.0.0.1/localhost) or the platform can't reach it and
    # reports "no open ports detected on 0.0.0.0". Binding 0.0.0.0 locally is
    # fine too — you can still reach it at http://localhost:<port>.
    #
    # Render (and most PaaS) provide the port to listen on via the PORT env var;
    # fall back to 8080 for local runs.
    port = int(os.environ.get("PORT", "8080"))
    print(f" * Waitress serving Michigan Pollution Map on http://0.0.0.0:{port}",
          flush=True)
    serve(application, host="0.0.0.0", port=port, threads=8)
