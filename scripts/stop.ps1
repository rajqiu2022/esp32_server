$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$data = if ($env:ESP_DATA_DIR) { $env:ESP_DATA_DIR } else { Join-Path $root 'data' }
$pidFile = Join-Path $data 'processes.json'
if (-not (Test-Path -LiteralPath $pidFile)) { return }
$pids = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json -AsHashtable
$wrapper = Join-Path $PSScriptRoot 'run.py'
foreach ($mode in @('voice','control')) {
    if (-not $pids.ContainsKey($mode)) { continue }
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($pids[$mode])" -ErrorAction SilentlyContinue
    if ($processInfo -and $processInfo.CommandLine.Contains($wrapper)) {
        Stop-Process -Id $pids[$mode]
        Write-Output "Stopped $mode."
    }
}
