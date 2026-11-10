# -*- mode: python ; coding: utf-8 -*-

from tkinter_icons import get_hook_dirs
from PyInstaller.utils.hooks import collect_all

miniaudio_datas, miniaudio_binaries, miniaudio_hiddenimports = collect_all('miniaudio')
cffi_datas, cffi_binaries, cffi_hiddenimports = collect_all('cffi')
pystray_datas, pystray_binaries, pystray_hiddenimports = collect_all('pystray')

a = Analysis(
    ['Seblue.pyw'],
    pathex=[],
    binaries=miniaudio_binaries + cffi_binaries + pystray_binaries,
    datas=[('assets/Sony-DTS-Sound.mp3', 'assets'),
           ('assets/cover-art.png', 'assets'),
           ('assets/seblue.ico', 'assets'),
           ('assets/seblue.png', 'assets')] + miniaudio_datas + cffi_datas + pystray_datas,
    hiddenimports=(['comtypes.stream', 'winrt.windows.media.control',
                    'winrt.windows.storage.streams'] + miniaudio_hiddenimports
                   + cffi_hiddenimports + pystray_hiddenimports + ['_cffi_backend']),
    hookspath=get_hook_dirs(),
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
    a.binaries,
    a.datas,
    [],
    name='SeBlue',
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
    icon=['assets/seblue.ico'],
)
