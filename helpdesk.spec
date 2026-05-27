# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Collecte les dépendances de packages complexes
datas = [
    ('static',   'static'),    # fichiers frontend
    ('routers',  'routers'),   # modules router
]

# Inclure la base SQLite si elle existe déjà
if os.path.exists('ticketing.db'):
    datas.append(('ticketing.db', '.'))

# Dépendances cachées nécessaires pour FastAPI / SQLAlchemy / Jose
hiddenimports = [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'anyio',
    'anyio._backends._asyncio',
    'email_validator',
    'multipart',
    'python_multipart',
    'jose',
    'jose.jwt',
    'bcrypt',
    'passlib',
    'passlib.handlers.bcrypt',
    'sqlalchemy.dialects.sqlite',
    'reportlab',
    'reportlab.graphics',
    'reportlab.platypus',
]

a = Analysis(
    ['launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'PIL'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HelpDesk IT',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # pas de fenêtre console
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='HelpDesk IT',
)
