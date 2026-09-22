# -*- mode: python ; coding: utf-8 -*-


from PyInstaller.utils.hooks import collect_data_files


a = Analysis(
    ['desktop/entry.py'],
    pathex=['.', 'src'],
    binaries=[],
    datas=[('desktop/frontend', 'desktop/frontend')]
    + collect_data_files('agent', includes=['**/*.md']),
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name='UpAgent',
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
)
