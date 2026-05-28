# Release process

This project ships releases via GitHub Releases. The full automation lives in
`.github/workflows/release.yml`; this doc covers what to do as a human.

## TL;DR cut a release

```bash
# 1. Ensure main is green and you have committed everything you want shipped.
git switch main
git pull --ff-only
bash scripts/check_ci_smoke.sh  # quick local pre-flight

# 2. Pick a semver tag. Prerelease tags ending in -alpha, -beta, or -rc are
#    automatically marked as prerelease on GitHub.
TAG=v0.1.0
git tag -a "${TAG}" -m "Release ${TAG}"
git push origin "${TAG}"

# 3. Watch the Release workflow run:
#    https://github.com/<owner>/seccomp-privacy-platform/actions/workflows/release.yml
```

When the workflow finishes you get:

- A new GitHub Release page at `https://github.com/<owner>/<repo>/releases/tag/${TAG}`
- All artifacts attached: bridge binaries (Linux gnu+musl, Linux aarch64,
  Windows MSVC, macOS arm64+x86_64), PyInstaller CLI bundles (Linux, Windows,
  macOS), source tarball, and matching `.sha256` files.
- A Docker image pushed to `ghcr.io/<owner>/<repo>:${TAG}` and
  `ghcr.io/<owner>/<repo>:latest`.

## Artifact list

| Artifact                                                 | Purpose                                                                         |
| -------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `bridge-<target>.tar.gz` (or `.zip` on Windows)          | Standalone Rust bridge binary per target triple                                 |
| `seccomp-privacy-cli-<host>.tar.gz` (or `.zip`)          | PyInstaller-bundled `seccomp-sse-client`, `seccomp-record-recovery-service`, `seccomp-init-metadata-db` |
| `console-static-<tag>.tar.gz`                            | Operator console SPA (Vite + React + Tailwind, built static assets) |
| `seccomp-privacy-platform-<tag>-source.tar.gz`           | `git archive` source snapshot                                                   |
| `ghcr.io/<owner>/<repo>:<tag>`                           | Docker image with bridge binary + Python venv + first-party scripts             |
| `*.sha256`                                               | One per artifact, lets users verify integrity                                   |

## Verifying artifacts

Every archive has a matching `.sha256` file next to it on the Release page:

```bash
shasum -a 256 -c bridge-x86_64-unknown-linux-gnu.tar.gz.sha256
```

For the Docker image:

```bash
docker pull ghcr.io/<owner>/seccomp-privacy-platform:v0.1.0
docker run --rm ghcr.io/<owner>/seccomp-privacy-platform:v0.1.0 bridge --help
```

## Building artifacts locally

For dry-runs or one-off binaries on a developer machine, use the shipped
helper. It detects available toolchains and skips steps it cannot do
locally rather than failing the whole run.

```bash
# All defaults: bridge + PyInstaller (if installed) + source tarball,
# tagged from git describe and written under dist/release/.
bash scripts/build_release_bundle.sh

# Skip the slowest steps if you only need one artifact.
bash scripts/build_release_bundle.sh --skip-pyinstaller --skip-source

# Include the docker image (requires docker daemon access).
bash scripts/build_release_bundle.sh --docker

# Override the tag used in archive names.
RELEASE_TAG=v0.1.0 bash scripts/build_release_bundle.sh
```

The script writes a `dist/release/release-manifest.json` summarizing what
was produced so CI logs and humans see a consistent inventory.

## Versioning

We use semantic versioning. Tag names must start with `v`:

- `v0.1.0` -> stable release
- `v0.1.0-rc.1`, `v0.1.0-beta.2`, `v0.1.0-alpha.1` -> auto-marked prerelease

## When the workflow fails

The release workflow is idempotent. If a single job fails (for example
`cross` choking on aarch64), you can:

1. Investigate the failure in the Actions UI.
2. Push a fix, retag (`git tag -d v0.1.0 && git tag v0.1.0 && git push --force origin v0.1.0`).
3. Or re-run only the failed jobs from the Actions UI (matrix builds rebuild
   only the failed shards; the `create-release` job will attach whatever
   artifacts are present).

Do **not** force-push tags casually if a release was already advertised; cut
a new patch version instead.

## Adding new artifacts

To ship a new binary in a release:

1. If it is a Python CLI, add a PyInstaller spec under
   `packaging/pyinstaller/` and add a build step to the `build-python-bundles`
   job in `release.yml`.
2. If it is a Rust binary, add a new crate or binary target in `bridge/` and
   extend the `build-bridge` matrix.
3. If it is a config bundle or static asset, add it to the source tarball or
   to the Dockerfile and update the artifact table above.

Whenever artifact filenames change, also update `scripts/build_release_bundle.sh`
so local builds match CI.
