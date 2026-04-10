# seccomp-privacy-platform

This repository is now organized as a multi-module workspace:

- `a-psi/`: Private Join and Compute workflow, job orchestration, and policy release logic
- `sse/`: Searchable symmetric encryption service and client implementation
- `bridge/`: Integration layer placeholder for exporting SSE-filtered records into PJC inputs

## Recommended entrypoints

### a-psi

```bash
cd a-psi
```

From there, use the existing `moduleA_psi/scripts/*` and `private-join-and-compute/` workflow.

### sse

```bash
cd sse
```

Create and use the local virtual environment before running the SSE entrypoints:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run_server.py --help
.venv/bin/python run_client.py --help
```

### bridge

`bridge/` is reserved for the upcoming integration layer between `sse` and `a-psi`.

## Notes

- Historical experiment outputs were moved under `a-psi/`.
- The original `a-psi` code layout is preserved inside `a-psi/`, so existing relative paths continue to work after changing into that directory.
