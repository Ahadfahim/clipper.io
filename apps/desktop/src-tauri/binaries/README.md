# Core sidecar

`tauri build` bundles `clipper-core-<target-triple>.exe` from this folder (Tauri appends the
target triple, e.g. `clipper-core-x86_64-pc-windows-msvc.exe`). It must start the Python core:
`clipper-core api`.

LOCAL-VERIFY: build it on Windows (PyInstaller one-folder build of `clipper.cli`, or a small
launcher that runs `uv run --project <install dir> clipper api`). The binary is gitignored.
Development builds don't start it; run `just dev-api` instead (or set `CLIPPER_SPAWN_CORE=1`).
