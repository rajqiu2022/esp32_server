param([string]$Python = $env:ESP_PYTHON, [switch]$ControlOnly)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Python) {
    $Python = Join-Path $root '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $Python)) {
        $Python = Join-Path (Split-Path $root) 'xiaozhi-server/.venv/Scripts/python.exe'
    }
}
if (-not (Test-Path -LiteralPath $Python)) { throw 'Python not found. Set ESP_PYTHON to a Python with the voice engine dependencies.' }
if (-not $env:ESP_MODELS_DIR) {
    $existingModels = Join-Path (Split-Path $root) 'xiaozhi-server/main/xiaozhi-server/models'
    if (Test-Path -LiteralPath $existingModels) { $env:ESP_MODELS_DIR = $existingModels }
}
$env:PYTHONUTF8 = '1'
$data = if ($env:ESP_DATA_DIR) { $env:ESP_DATA_DIR } else { Join-Path $root 'data' }
New-Item -ItemType Directory -Path $data -Force | Out-Null
$port = if ($env:ESP_PORT) { [int]$env:ESP_PORT } else { 8002 }
$wrapper = Join-Path $PSScriptRoot 'run.py'
$pidFile = Join-Path $data 'processes.json'
$pids = if (Test-Path -LiteralPath $pidFile) { Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json -AsHashtable } else { @{} }
foreach ($mode in @('control', 'voice')) {
    if ($mode -eq 'voice' -and $ControlOnly) { continue }
    $listenPort = if ($mode -eq 'control') { $port } else { 8000 }
    $listener = Get-NetTCPConnection -LocalPort $listenPort -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener[0].OwningProcess)"
        if (-not $processInfo.CommandLine.Contains($wrapper)) { throw "Port $listenPort is in use by another service." }
        Write-Output "$mode is already listening on port $listenPort."
        continue
    }
    $proc = Start-Process -FilePath $Python -ArgumentList @('-u', ('"' + $wrapper + '"'), $mode) -WindowStyle Hidden -PassThru -WorkingDirectory $root -RedirectStandardOutput (Join-Path $data "$mode.stdout.log") -RedirectStandardError (Join-Path $data "$mode.stderr.log")
    $pids[$mode] = $proc.Id
    $pids | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding utf8
    if ($mode -eq 'control') {
        $ready = $false
        for ($i=0; $i -lt 30; $i++) {
            try { $null = Invoke-RestMethod "http://127.0.0.1:$port/api/health"; $ready=$true; break } catch { Start-Sleep -Milliseconds 500 }
        }
        if (-not $ready) { throw 'Control service failed to start; check data/control.stderr.log.' }
    }
    Write-Output "$mode started, PID $($proc.Id)."
}
Write-Output "Control panel: http://127.0.0.1:$port/"
