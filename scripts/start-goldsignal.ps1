param([ValidateSet("start", "stop", "status")] [string] $Action = "status")

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

$Services = @(
    @{ Name = "api";    Match = "uvicorn goldsignal.api:app"; Args = "-m uvicorn goldsignal.api:app --host 127.0.0.1 --port 8011"; Log = "api.log" },
    @{ Name = "worker"; Match = "goldsignal.worker";         Args = "-m goldsignal.worker";                                      Log = "worker.log" },
    @{ Name = "relay";  Match = "goldsignal.relay";          Args = "-m goldsignal.relay ryaze-relay.pem --url https://goldsignal.ryaze.my.id"; Log = "relay.log" }
)

function Get-ServiceProcess([string] $Match) {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -match [regex]::Escape($Match) }
}

switch ($Action) {
    "status" {
        foreach ($service in $Services) {
            $running = @(Get-ServiceProcess $service.Match)
            "{0,-7} {1}" -f $service.Name, $(if ($running) { "running (PID " + ($running.ProcessId -join ", ") + ")" } else { "stopped" })
        }
    }
    "stop" {
        foreach ($service in $Services) {
            foreach ($process in @(Get-ServiceProcess $service.Match)) {
                Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
            }
            "{0,-7} stopped" -f $service.Name
        }
    }
    "start" {
        foreach ($service in $Services) {
            if (Get-ServiceProcess $service.Match) {
                "{0,-7} already running" -f $service.Name
                continue
            }
            $log = Join-Path $Logs ($service.Log -replace '\.log$', '')
            Start-Process -FilePath $Python -WindowStyle Hidden -WorkingDirectory $Root `
                -ArgumentList $service.Args `
                -RedirectStandardOutput "$log.out.log" -RedirectStandardError "$log.err.log"
            "{0,-7} started -> {1}" -f $service.Name, "$log.out.log"
        }
    }
}
