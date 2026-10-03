# Target environment (the user's machine)

Clipper.io runs on one Windows PC. Code written elsewhere (e.g. a Linux cloud session) must target this machine.

| Item | Value |
|---|---|
| OS | Windows 11 Pro (build 26200) |
| CPU | AMD Ryzen 7 9800X3D (8 cores) |
| RAM | 32 GB |
| GPU | NVIDIA GeForce RTX 5080, 16 GB VRAM (Blackwell; **PyTorch needs CUDA 12.8+ / `cu128` wheels**). Driver 616.56 |
| NVENC | Yes (RTX 5080). Plan for up to 3 concurrent encode sessions |
| Project path | `D:\Clipper.io` (data folder `D:\Clipper.io\data`, ~400 GB free on D:) |
| Python | 3.13 installed via Miniconda; project pins **3.12** through **uv** (uv 0.12.x installed) |
| Node | 24.x, npm 11.x (pnpm via corepack) |
| Rust | cargo 1.96 (for Tauri v2) |
| ffmpeg | 8.1 essentials build at `C:\ffmpeg\bin` (has h264_nvenc, libass) |
| yt-dlp | 2026.03.x |
| Browser | Google Chrome; a dedicated "Clipper" Chrome profile hosts the Companion extension |
| Claude | Claude Code logged in with the user's Claude plan. **No `ANTHROPIC_API_KEY`**; agents must use the plan login |
| GitHub CLI | not installed |

## What only works on this machine
- CUDA / WhisperX / pyannote on the GPU, NVENC encoding
- Building and running the Tauri app and the Windows installer
- The Companion extension inside the real Chrome profile (logins for Vyro, Whop, YouTube Studio, TikTok Studio, Instagram)
- Live Discord bot (token stored in Windows Credential Manager)
- Real agent runs on the Claude plan login

Everything else (Python core, MCP tools with fakes, EDL engine on CPU, API, UI in a browser with fixtures, bot logic, extension logic) can be built and tested anywhere.
