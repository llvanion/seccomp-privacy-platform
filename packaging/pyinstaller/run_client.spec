# PyInstaller spec for sse/run_client.py
# Build: python -m PyInstaller --clean --noconfirm packaging/pyinstaller/run_client.spec

import os
from pathlib import Path

# spec_root is set by PyInstaller; fall back to CWD when running stand-alone.
spec_root = Path(globals().get("SPECPATH", os.getcwd())).resolve()
repo_root = spec_root.parents[1]
sse_root = repo_root / "sse"

block_cipher = None

a = Analysis(
    [str(sse_root / "run_client.py")],
    pathex=[str(repo_root), str(sse_root), str(repo_root / "scripts")],
    binaries=[],
    datas=[
        (str(sse_root / "config"), "sse/config"),
        (str(sse_root / "schemes"), "sse/schemes"),
        (str(sse_root / "toolkit"), "toolkit"),
    ],
    hiddenimports=[
        "services.record_recovery",
        "services.record_recovery.client",
        "services.record_recovery.encrypted_record_store",
        "services.record_recovery.bootstrap",
        "toolkit",
        "toolkit.platform_policy",
        "toolkit.encrypted_record_store",
        "toolkit.record_recovery_client",
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
    name="seccomp-sse-client",
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
    name="seccomp-sse-client",
)
