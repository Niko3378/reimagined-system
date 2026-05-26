@echo off
echo ============================================
echo        HelpDesk IT - Ticketing System
echo ============================================
echo.
echo Demarrage du serveur...
echo Ouvrez votre navigateur sur : http://localhost:8000
echo.
echo Pour arreter le serveur, fermez cette fenetre.
echo.
cd /d "%~dp0"
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
