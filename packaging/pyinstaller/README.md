# PyInstaller bundles

These specs build self-contained CLI executables for the project's most
common entry points so a release can ship binaries that do not require
the user to install a Python interpreter.

## Local build

```bash
python -m pip install pyinstaller
python -m pip install -r sse/requirements.txt

python -m PyInstaller --clean --noconfirm packaging/pyinstaller/run_client.spec
python -m PyInstaller --clean --noconfirm packaging/pyinstaller/run_record_recovery_service.spec
python -m PyInstaller --clean --noconfirm packaging/pyinstaller/init_metadata_db.spec
```

Outputs land under `dist/<binary-name>/`. Each output directory contains
the binary plus its dynamic dependencies; archive the directory whole.

## What gets bundled

| Spec                                  | Source script                                | Output binary                          |
| ------------------------------------- | -------------------------------------------- | -------------------------------------- |
| `run_client.spec`                     | `sse/run_client.py`                          | `seccomp-sse-client`                   |
| `run_record_recovery_service.spec`    | `scripts/run_record_recovery_service.py`     | `seccomp-record-recovery-service`      |
| `init_metadata_db.spec`               | `scripts/init_metadata_db.py`                | `seccomp-init-metadata-db`             |

The CI release workflow (`.github/workflows/release.yml`) builds these on
Linux x86_64, Windows x86_64, and macOS arm64 runners and uploads each as
a release artifact.

## Limitations

- The bundles only cover the listed CLIs. Other scripts under `scripts/`
  still need a Python interpreter. Use the source tarball or the Docker
  image when you need the full surface area.
- The PJC binaries from `a-psi/private-join-and-compute/` are not bundled
  here; they are built separately via Bazel and bundled only through the
  Docker release.
