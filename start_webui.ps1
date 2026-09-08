# AICoverGen Quick Start - PowerShell
# วางใน PowerShell แล้วกด Enter

Write-Host ""
Write-Host "  /\     " -ForegroundColor Cyan -NoNewline; Write-Host "AI " -ForegroundColor White -NoNewline; Write-Host "COVER " -ForegroundColor Cyan -NoNewline; Write-Host "GEN" -ForegroundColor White
Write-Host " /  \    " -ForegroundColor Cyan -NoNewline; Write-Host "WebUI Starting..." -ForegroundColor Gray
Write-Host "/    \   " -ForegroundColor Cyan -NoNewline; Write-Host "RTX 2050 Optimized" -ForegroundColor Gray
Write-Host ""

# Kill old processes
$old = netstat -aon | Select-String ":7860" | Select-String "LISTENING"
if ($old) {
    $oldPid = ($old -split '\s+')[-1]
    Write-Host "  [x] Killing old process PID: $oldPid" -ForegroundColor Yellow
    taskkill /F /PID $oldPid 2>$null | Out-Null
    Start-Sleep -Seconds 2
}

# Cache directories redirection to D:
$env:HF_HOME = "D:\AI_Cache\huggingface"
$env:TORCH_HOME = "D:\AI_Cache\torch"
$env:PIP_CACHE_DIR = "D:\AI_Cache\pip"

# Start WebUI
Write-Host "  [>] Starting WebUI..." -ForegroundColor Cyan
$proc = Start-Process -FilePath "D:\Code\AICoverGen\.venv\Scripts\python.exe" `
    -ArgumentList "src/webui.py --listen --listen-port 7860" `
    -WorkingDirectory "D:\Code\AICoverGen" `
    -PassThru

# Wait for ready
Write-Host "  [~] Waiting for server..." -ForegroundColor Gray -NoNewline
$ready = $false
for ($i = 1; $i -le 15; $i++) {
    Start-Sleep -Seconds 1
    $port = Test-NetConnection -ComputerName 127.0.0.1 -Port 7860 -InformationLevel Quiet -WarningAction SilentlyContinue
    if ($port) { $ready = $true; break }
    Write-Host "." -ForegroundColor Gray -NoNewline
}
Write-Host ""

if ($ready) {
    Write-Host ""
    Write-Host "  +--------------------------------------+" -ForegroundColor Green
    Write-Host "  |                                      |" -ForegroundColor Green
    Write-Host "  |   WebUI is running!                  |" -ForegroundColor Green
    Write-Host "  |                                      |" -ForegroundColor Green
    Write-Host "  |   http://127.0.0.1:7860              |" -ForegroundColor White
    Write-Host "  |                                      |" -ForegroundColor Green
    Write-Host "  +--------------------------------------+" -ForegroundColor Green
    Write-Host ""
    Write-Host "  First time?" -ForegroundColor Cyan
    Write-Host "    1. Download model tab -> choose voice model" -ForegroundColor Gray
    Write-Host "    2. Generate tab -> enter YouTube URL -> Generate!" -ForegroundColor Gray
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "  [!] Failed to start. Check D:\Code\AICoverGen\webui.log" -ForegroundColor Red
    Write-Host ""
}
