# PyInstaller spec for scripts/run_record_recovery_service.py

import os
from pathlib import Path

spec_root = Path(globals().get("SPECPATH", os.getcwd())).resolve()
repo_root = spec_root.parents[1]

block_cipher = None

a = Analysis(
    [str(repo_root / "scripts" / "run_record_recovery_service.py")],
    pathex=[
        str(repo_root),
        str(repo_root / "sse"),
        str(repo_root / "scripts"),
    ],
    binaries=[],
    datas=[
        (str(repo_root / "schemas"), "schemas"),
        (str(repo_root / "config"), "config"),
        (str(repo_root / "sse" / "toolkit"), "toolkit"),
    ],
    hiddenimports=[
        "services.record_recovery",
        "services.record_recovery.launcher",
        "services.record_recovery.bootstrap",
        "services.record_recovery.http_service",
        "services.record_recovery.runtime",
        "services.record_recovery.authz",
        "services.record_recovery.audit",
        "toolkit",
        "toolkit.platform_policy",
        "toolkit.record_recovery_authz",
        "toolkit.record_recovery_client",
        "toolkit.record_recovery_common",
        "toolkit.record_recovery_http_service",
        "toolkit.encrypted_record_store",
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
    name="seccomp-record-recovery-service",
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
    name="seccomp-record-recovery-service",
)
