# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('cloudtool/assets', 'cloudtool/assets'), ('browser_extension', 'browser_extension')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# The bundled Python runtime may contribute an ICU DLL with version-suffixed
# exports. Qt for Windows needs the Windows ICU API instead. Do not shadow it.
a.binaries = [entry for entry in a.binaries if entry[0].lower() not in {'icuuc.dll', 'icudt78.dll'}]
# Exclude development-only downloaded browser data.
a.datas = [entry for entry in a.datas if '.local-browsers' not in entry[0].replace('\\', '/').split('/')]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CloudDesk',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
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
    name='CloudDesk',
)

