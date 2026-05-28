# PyInstaller spec for scripts/init_metadata_db.py

import os
from pathlib import Path

spec_root = Path(globals().get("SPECPATH", os.getcwd())).resolve()
repo_root = spec_root.parents[1]

block_cipher = None

a = Analysis(
    [str(repo_root / "scripts" / "init_metadata_db.py")],
    pathex=[str(repo_root), str(repo_root / "scripts")],
    binaries=[],
    datas=[
        (str(repo_root / "migrations"), "migrations"),
    ],
    hiddenimports=[
        "metadata_db",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
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
    name="seccomp-init-metadata-db",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="seccomp-init-metadata-db",
)
