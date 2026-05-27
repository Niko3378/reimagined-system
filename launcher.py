"""
HelpDesk IT — Launcher
Démarre le serveur uvicorn puis ouvre le navigateur.
"""
import os
import sys
import time
import webbrowser
import threading
import shutil
import urllib.request
import traceback

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

# ── Log fichier pour les erreurs de démarrage ─────────────────────────────────
LOG_FILE = os.path.join(DATA_DIR, "helpdesk.log")


def log(msg):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


# Copie la base SQLite si elle n'existe pas encore dans DATA_DIR
DB_SRC  = os.path.join(BASE_DIR, "ticketing.db")
DB_DEST = os.path.join(DATA_DIR, "ticketing.db")
if os.path.exists(DB_SRC) and not os.path.exists(DB_DEST):
    shutil.copy2(DB_SRC, DB_DEST)
    log(f"Base de données copiée vers {DB_DEST}")

# Indique à l'app où trouver la BDD et les fichiers statiques
os.environ["HELPDESK_DB_PATH"]     = DB_DEST
os.environ["HELPDESK_STATIC_PATH"] = os.path.join(BASE_DIR, "static")
os.environ["HELPDESK_BASE_DIR"]    = BASE_DIR

# Ajoute BASE_DIR au path pour que les imports fonctionnent
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

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
            log("Navigateur ouvert")
            return
        except Exception:
            pass
    log("WARN: serveur non disponible après 30 secondes")


def start_server():
    """Lance uvicorn avec l'app importée directement (compatible PyInstaller)."""
    try:
        log(f"Démarrage — BASE_DIR={BASE_DIR} DATA_DIR={DATA_DIR}")

        # console=False (PyInstaller) met stdout/stderr à None,
        # ce qui fait planter le logging d'uvicorn — on les redirige vers le log
        if sys.stdout is None:
            sys.stdout = open(LOG_FILE, "a", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(LOG_FILE, "a", encoding="utf-8")

        from main import app
        import uvicorn
        uvicorn.run(app, host=HOST, port=PORT, log_config=None)
    except Exception:
        log("ERREUR démarrage serveur :\n" + traceback.format_exc())
        # Afficher l'erreur dans une boîte de dialogue Windows
        try:
            import ctypes
            err = traceback.format_exc()
            ctypes.windll.user32.MessageBoxW(
                0,
                f"HelpDesk IT n'a pas pu démarrer.\n\nLog : {LOG_FILE}\n\n{err[:500]}",
                "HelpDesk IT — Erreur",
                0x10  # MB_ICONERROR
            )
        except Exception:
            pass


if __name__ == "__main__":
    threading.Thread(target=wait_for_server, daemon=True).start()
    start_server()
