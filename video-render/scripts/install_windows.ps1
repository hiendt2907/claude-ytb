$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

$python = Get-Command py -ErrorAction SilentlyContinue
if ($python) {
    $pythonCmd = "py"
    $pythonArgs = @("-3")
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python 3 is required. Install it from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'."
    }
    $pythonCmd = "python"
    $pythonArgs = @()
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
    } else {
        throw "ffmpeg is required. Install it from https://www.gyan.dev/ffmpeg/builds/ and add bin\ to PATH."
    }
}

& $pythonCmd @pythonArgs -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install .

Write-Host ""
Write-Host "Installed. Start the app with:"
Write-Host "  .\scripts\run_windows.ps1"

