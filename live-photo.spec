# -*- mode: python ; coding: utf-8 -*-

import sys

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('static/index.html', 'static'),
    ],
    hiddenimports=[
        'pillow_heif',
        'PIL',
        'httpx',
        'openai',
        'fastapi',
        'uvicorn',
        'uvicorn.loops.auto',
        'uvicorn.protocols.http.auto',
        'pydantic',
        'dotenv',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='live-photo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='live-photo-dist',
)
