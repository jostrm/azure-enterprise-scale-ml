# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from pathlib import Path

root = Path(SPECPATH)
datas = collect_data_files('sv_ttk') + [(str(root / 'template-files'), 'template-files')]
# Published helpers are loaded dynamically after source/hash verification.
runtime_imports = ['urllib.request', 'urllib.error', 'urllib.parse', 'ctypes.wintypes', 'zlib']

a = Analysis(
    [str(root / 'src' / 'api_sidecar.py')],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=['fastapi', 'uvicorn', 'winpty', 'src.catalog_worker', 'src.catalog_parameters',
                   'jsonschema', 'jsonschema_specifications', *runtime_imports],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='aifactory-api',
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
    name='aifactory-api',
)
