"""
HelpDesk IT — Launcher
Démarre le serveur uvicorn puis ouvre le navigateur.
"""
import os
import sys
import time
import subprocess
import webbrowser
import threading
import shutil
import urllib.request

# ── Chemin de base (PyInstaller ou dev) ──────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
    APP_DIR  = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR  = BASE_DIR

# ── Répertoire de données utilisateur (writable) ─────────────────────────────
DATA_DIR = os.path.join(os.environ.get("APPDATA", APP_DIR), "HelpDesk IT")
os.makedirs(DATA_DIR, exist_ok=True)

# Copie la base SQLite si elle n'existe pas encore dans DATA_DIR
DB_SRC  = os.path.join(BASE_DIR, "helpdesk.db")
DB_DEST = os.path.join(DATA_DIR, "helpdesk.db")
if os.path.exists(DB_SRC) and not os.path.exists(DB_DEST):
    shutil.copy2(DB_SRC, DB_DEST)

# Indique à l'app où trouver la BDD et les fichiers statiques
os.environ["HELPDESK_DB_PATH"]     = DB_DEST
os.environ["HELPDESK_STATIC_PATH"] = os.path.join(BASE_DIR, "static")
os.environ["HELPDESK_BASE_DIR"]    = BASE_DIR

PORT = 8000
HOST = "127.0.0.1"
URL  = f"http://{HOST}:{PORT}"


def wait_for_server():
    """Attend que le serveur réponde, puis ouvre le navigateur."""
    for _ in range(30):
        time.sleep(1)
        try:
            urllib.request.urlopen(URL, timeout=1)
            webbrowser.open(URL)
            return
        except Exception:
            pass


def start_server():
    """Lance uvicorn dans le même processus."""
    # Ajoute BASE_DIR au path pour que les imports fonctionnent
    sys.path.insert(0, BASE_DIR)
    os.chdir(BASE_DIR)

    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    threading.Thread(target=wait_for_server, daemon=True).start()
    start_server()
