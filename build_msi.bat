@echo off
setlocal enabledelayedexpansion
title HelpDesk IT — Build MSI
echo.
echo ============================================================
echo   HelpDesk IT — Construction du MSI
echo ============================================================
echo.

:: ── Vérification Python ──────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python non trouvé dans le PATH.
    pause & exit /b 1
)

:: ── Installation PyInstaller ──────────────────────────────────
echo [1/5] Vérification de PyInstaller...
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo       Installation de PyInstaller...
    python -m pip install pyinstaller --quiet
    if errorlevel 1 ( echo [ERREUR] Echec installation PyInstaller & pause & exit /b 1 )
)
echo       OK

:: ── Vérification WiX Toolset ─────────────────────────────────
echo [2/5] Vérification de WiX Toolset...
set WIX_CANDLE=
for %%D in (
    "C:\Program Files (x86)\WiX Toolset v3.14\bin"
    "C:\Program Files (x86)\WiX Toolset v3.11\bin"
    "C:\Program Files\WiX Toolset v3.14\bin"
    "C:\Program Files\WiX Toolset v3.11\bin"
) do (
    if exist "%%~D\candle.exe" set "WIX_CANDLE=%%~D\candle.exe" & set "WIX_LIGHT=%%~D\light.exe" & set "WIX_HEAT=%%~D\heat.exe"
)

if "!WIX_CANDLE!"=="" (
    echo.
    echo [INFO] WiX Toolset non trouvé.
    echo       Télécharge et installe WiX v3 depuis :
    echo       https://github.com/wixtoolset/wix3/releases/latest
    echo       Puis relance ce script.
    echo.
    start https://github.com/wixtoolset/wix3/releases/latest
    pause & exit /b 1
)
echo       Trouvé : !WIX_CANDLE!

:: ── Build PyInstaller ─────────────────────────────────────────
echo [3/5] Build PyInstaller (peut prendre quelques minutes)...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
python -m PyInstaller helpdesk.spec --noconfirm
if errorlevel 1 ( echo [ERREUR] PyInstaller a échoué & pause & exit /b 1 )
echo       OK — dossier dist\HelpDesk IT créé

:: ── Harvest des fichiers avec heat.exe ───────────────────────
echo [4/5] Génération du fichier WiX pour les ressources...
"!WIX_HEAT!" dir "dist\HelpDesk IT" ^
    -nologo -sfrag -srd -scom -sreg ^
    -gg -gl -cg AppFilesGroup ^
    -dr INSTALLDIR ^
    -out app_files.wxs
if errorlevel 1 ( echo [ERREUR] heat.exe a échoué & pause & exit /b 1 )
echo       OK — app_files.wxs généré

:: ── Compilation et édition de liens WiX ──────────────────────
echo [5/5] Compilation du MSI...
"!WIX_CANDLE!" installer.wxs app_files.wxs -nologo -out obj\
if errorlevel 1 ( echo [ERREUR] candle.exe a échoué & pause & exit /b 1 )

"!WIX_LIGHT!" obj\installer.wixobj obj\app_files.wixobj ^
    -nologo ^
    -ext WixUIExtension ^
    -cultures:fr-FR ^
    -out "HelpDesk_IT_Setup.msi"
if errorlevel 1 ( echo [ERREUR] light.exe a échoué & pause & exit /b 1 )

echo.
echo ============================================================
echo   SUCCÈS : HelpDesk_IT_Setup.msi généré !
echo ============================================================
echo.
explorer /select,"HelpDesk_IT_Setup.msi"
pause
