# -*- mode: python ; coding: utf-8 -*-
import glob

data_files = []
for pattern in ['*.ico', '*.ogg', '*.gif']:
    for filepath in glob.glob(pattern):
        data_files.append((filepath, '.'))

a = Analysis(
    ['dmod.py'],
    pathex=[],
    binaries=[],
    datas=data_files,
    hiddenimports=[
        '_cffi_backend',
        'taskbarz',
        'blueaway',
        'blueaway_core',
        'test_engine',
        'win32api',
        'win32con',
        'win32security',
        'win32gui',
        'win32process',
        'uiautomation',
        'comtypes',
        'comtypes.stream',
        'pynput.keyboard._win32',
        'pynput.mouse._win32'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

EXCLUDED_EXTENSIONS = ('.bat', '.bak', '.pyc')

a.datas = [
    item for item in a.datas 
    if not item[0].lower().endswith(EXCLUDED_EXTENSIONS)
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DMod',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
    uac_admin=True,
)