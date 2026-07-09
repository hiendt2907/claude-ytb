$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".\.venv\Scripts\video-render.exe")) {
    throw "Local install not found. Run .\scripts\install_windows.ps1 first."
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "ffmpeg is required but was not found in PATH. Reopen PowerShell after install, or install FFmpeg and add its bin folder to PATH."
}

& .\.venv\Scripts\video-render.exe
