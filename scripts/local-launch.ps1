param(
  [ValidateSet("start", "stop", "status", "restart")]
  [string]$Action = "start",
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$Python = Join-Path $Root ".venv\Scripts\python.exe"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host ""; Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

function Get-PythonProcs([string]$pattern) {
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern }
}

function Test-Port([int]$port) {
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect("127.0.0.1", $port, $null, $null)
    $ok = $iar.AsyncWaitHandle.WaitOne(300)
    $connected = $ok -and $client.Connected
    $client.Close()
    return $connected
  } catch { return $false }
}

function Start-Worker {
  if (Get-PythonProcs "goldsignal\.worker") { Write-Host "    worker already running" -ForegroundColor DarkGray; return }
  Write-Step "Starting worker..."
  Start-Process -FilePath $Python -WindowStyle Hidden -WorkingDirectory $Root `
    -ArgumentList "-m goldsignal.worker" `
    -RedirectStandardOutput (Join-Path $Logs "worker.out.log") `
    -RedirectStandardError (Join-Path $Logs "worker.err.log")
}

function Start-Api {
  if (Test-Port 8011) { Write-Host "    web already listening on 8011" -ForegroundColor DarkGray; return }
  Write-Step "Starting web server on http://127.0.0.1:8011 ..."
  Start-Process -FilePath $Python -WindowStyle Hidden -WorkingDirectory $Root `
    -ArgumentList "-m uvicorn goldsignal.api:app --host 127.0.0.1 --port 8011" `
    -RedirectStandardOutput (Join-Path $Logs "api.out.log") `
    -RedirectStandardError (Join-Path $Logs "api.err.log")
}

function Wait-Api([int]$seconds = 30) {
  $deadline = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-Port 8011) { return $true }
    Start-Sleep -Milliseconds 400
  }
  return $false
}

switch ($Action) {
  "stop" {
    Write-Step "Stopping Goldsignal..."
    $targets = @()
    $targets += @(Get-PythonProcs "goldsignal\.worker")
    $targets += @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
      Where-Object { $_.CommandLine -match "uvicorn goldsignal\.api:app" })
    foreach ($p in $targets) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host "Goldsignal stopped." -ForegroundColor Green
  }
  "status" {
    $worker = @(Get-PythonProcs "goldsignal\.worker").Count
    $api = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
      Where-Object { $_.CommandLine -match "uvicorn goldsignal\.api:app" }).Count
    Write-Host ("worker  {0}" -f $(if ($worker) { "running" } else { "stopped" }))
    Write-Host ("web     {0} (port 8011 {1})" -f $(if ($api) { "running" } else { "stopped" }), $(if (Test-Port 8011) { "open" } else { "closed" }))
  }
  "restart" {
    & $PSCommandPath -Action stop
    Start-Sleep -Seconds 1
    & $PSCommandPath -Action start
  }
  default {
    Write-Step "Preparing Goldsignal..."

    if (-not (Test-Path $Python)) {
      $base = Get-Command python -ErrorAction SilentlyContinue
      $baseArgs = @()
      if (-not $base) {
        $base = Get-Command py -ErrorAction SilentlyContinue
        $baseArgs = @("-3")
        if (-not $base) { Fail "Python not found. Install Python 3.11+ then run this again." }
      }
      Write-Step "Creating virtual environment (first run)..."
      & $base.Source @baseArgs -m venv .venv
      if ($LASTEXITCODE -ne 0) { Fail "Could not create .venv" }
      Write-Step "Installing Python requirements (first run)..."
      & $Python -m pip install --upgrade pip
      & $Python -m pip install -r requirements.txt
      if ($LASTEXITCODE -ne 0) { Fail "pip install failed. Check your internet connection." }
    }

    if (-not (Test-Path (Join-Path $Root ".env")) -and (Test-Path (Join-Path $Root ".env.example"))) {
      Write-Step "Creating .env from .env.example"
      Copy-Item ".env.example" ".env"
    }

    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
      Fail "Node.js/npm not found. Install Node 20+ then run this again."
    }

    if (-not (Test-Path (Join-Path $Root "node_modules"))) {
      Write-Step "Installing Node dependencies (first run)..."
      & npm.cmd ci
      if ($LASTEXITCODE -ne 0) { Fail "npm ci failed." }
    }

    Write-Step "Building dashboard..."
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { Fail "Dashboard build failed. See the messages above." }

    Write-Step "Preparing database..."
    & $Python -m goldsignal.store
    if ($LASTEXITCODE -ne 0) { Fail "Database setup failed." }

    Start-Worker
    Start-Api

    if (Wait-Api 30) {
      Start-Sleep -Milliseconds 600
      if (-not $NoBrowser) { Start-Process "http://127.0.0.1:8011" }
      Write-Host ""
      Write-Host "Goldsignal is running at http://127.0.0.1:8011" -ForegroundColor Green
      Write-Host "Logs: $Logs" -ForegroundColor DarkGray
      Write-Host "To stop, run Stop Goldsignal.bat" -ForegroundColor DarkGray
    } else {
      Write-Host "Web server did not open port 8011. Check logs in $Logs" -ForegroundColor Red
      exit 1
    }
  }
}
