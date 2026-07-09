$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

$python = Get-Command py -ErrorAction SilentlyContinue
if ($python) {
    $pythonCmd = "py"
    $pythonArgs = @("-3")
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python is required only on the builder machine. Install Python 3.11+ to build the EXE."
    }
    $pythonCmd = "python"
    $pythonArgs = @()
}

& $pythonCmd @pythonArgs -m venv .build-venv
& .\.build-venv\Scripts\python.exe -m pip install --upgrade pip
& .\.build-venv\Scripts\python.exe -m pip install ".[build]"
& .\.build-venv\Scripts\python.exe .\scripts\prepare_ffmpeg_bundle.py

Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
Remove-Item -Force ".\dist\Video Render.exe" -ErrorAction SilentlyContinue

& .\.build-venv\Scripts\pyinstaller.exe `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "Video Render" `
    --add-data "src\ytb_pipeline\webui\templates;ytb_pipeline\webui\templates" `
    --add-binary ".build-assets\ffmpeg\ffmpeg.exe;ffmpeg" `
    --add-binary ".build-assets\ffmpeg\ffprobe.exe;ffmpeg" `
    src\ytb_pipeline\desktop.py

Write-Host "Created dist\Video Render.exe"

