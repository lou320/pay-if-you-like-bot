# ============================================================
#  Pay If You Like - Dual Bot Manager  (Windows PowerShell)
#  Usage:  .\run_bots.ps1 [start|stop|restart|status|logs]
# ============================================================

param(
    [string]$Command = "help"
)

$RepoRoot     = $PSScriptRoot
$AdminBotDir  = Join-Path $RepoRoot "admin_bot"
$VpnBotDir    = Join-Path $RepoRoot "vpn_bot"
$EnterpriseBotDir = Join-Path $RepoRoot "enterprise_bot"
$DashboardDir = Join-Path $RepoRoot "dashboard"
$VenvPython   = Join-Path $RepoRoot "venv\Scripts\python.exe"

$AdminBotLog  = Join-Path $RepoRoot "admin_bot.log"
$VpnBotLog    = Join-Path $RepoRoot "vpn_bot.log"
$EnterpriseBotLog = Join-Path $RepoRoot "enterprise_bot.log"
$DashboardLog = Join-Path $RepoRoot "dashboard.log"
$AdminBotErr   = Join-Path $RepoRoot "admin_bot.err.log"
$VpnBotErr     = Join-Path $RepoRoot "vpn_bot.err.log"
$EnterpriseBotErr = Join-Path $RepoRoot "enterprise_bot.err.log"
$DashboardErr  = Join-Path $RepoRoot "dashboard.err.log"
$AdminBotPid  = Join-Path $RepoRoot ".admin_bot.pid"
$VpnBotPid    = Join-Path $RepoRoot ".vpn_bot.pid"
$EnterpriseBotPid = Join-Path $RepoRoot ".enterprise_bot.pid"
$DashboardPid = Join-Path $RepoRoot ".dashboard.pid"

$DashUser = if ($env:DASH_USER) { $env:DASH_USER } else { "admin" }
$DashPass = if ($env:DASH_PASS) { $env:DASH_PASS } else { "changeme" }
$DashPort = if ($env:DASH_PORT) { $env:DASH_PORT } else { "5050" }

function Write-OK   { param($msg) Write-Host "[OK]  $msg" -ForegroundColor Green  }
function Write-Fail { param($msg) Write-Host "[ERR] $msg" -ForegroundColor Red    }
function Write-Info { param($msg) Write-Host "[>>]  $msg" -ForegroundColor Yellow }

function Start-PythonService {
    param(
        [string]$WorkingDirectory,
        [string]$ScriptName,
        [string]$StdOutLog,
        [string]$StdErrLog
    )

    return Start-Process -FilePath $VenvPython `
        -ArgumentList "-u", $ScriptName `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $StdOutLog `
        -RedirectStandardError $StdErrLog `
        -WindowStyle Hidden -PassThru
}

# --- Start ---
function Start-Bots {
    Write-Info "Starting all services..."

    Stop-Bots -Quiet

    if (-not (Test-Path $VenvPython)) {
        Write-Fail "venv not found at: $VenvPython"
        Write-Info "Create it with: python -m venv venv  then  pip install -r vpn_bot\requirements.txt"
        return
    }

    # Admin Bot
    Write-Info "Starting Admin Bot..."
    try {
        $adminProc = Start-PythonService -WorkingDirectory $AdminBotDir -ScriptName "bot.py" -StdOutLog $AdminBotLog -StdErrLog $AdminBotErr
        $adminProc.Id | Set-Content $AdminBotPid
        Start-Sleep -Seconds 2

        if (-not $adminProc.HasExited) {
            Write-OK "Admin Bot started (PID: $($adminProc.Id))  ->  log: $AdminBotLog"
        } else {
            Write-Fail "Admin Bot failed to start -- check $AdminBotLog and $AdminBotErr"
        }
    } catch {
        Write-Fail "Admin Bot failed to start -- $($_.Exception.Message)"
    }

    # VPN Bot
    Write-Info "Starting VPN Bot..."
    try {
        $vpnProc = Start-PythonService -WorkingDirectory $VpnBotDir -ScriptName "bot.py" -StdOutLog $VpnBotLog -StdErrLog $VpnBotErr
        $vpnProc.Id | Set-Content $VpnBotPid
        Start-Sleep -Seconds 2

        if (-not $vpnProc.HasExited) {
            Write-OK "VPN Bot started   (PID: $($vpnProc.Id))  ->  log: $VpnBotLog"
        } else {
            Write-Fail "VPN Bot failed to start -- check $VpnBotLog and $VpnBotErr"
        }
    } catch {
        Write-Fail "VPN Bot failed to start -- $($_.Exception.Message)"
    }

    # Enterprise Bot
    Write-Info "Starting Enterprise Bot..."
    try {
        $enterpriseProc = Start-PythonService -WorkingDirectory $EnterpriseBotDir -ScriptName "bot.py" -StdOutLog $EnterpriseBotLog -StdErrLog $EnterpriseBotErr
        $enterpriseProc.Id | Set-Content $EnterpriseBotPid
        Start-Sleep -Seconds 2

        if (-not $enterpriseProc.HasExited) {
            Write-OK "Enterprise Bot started (PID: $($enterpriseProc.Id))  ->  log: $EnterpriseBotLog"
        } else {
            Write-Fail "Enterprise Bot failed to start -- check $EnterpriseBotLog and $EnterpriseBotErr"
        }
    } catch {
        Write-Fail "Enterprise Bot failed to start -- $($_.Exception.Message)"
    }

    # Dashboard
    Write-Info "Starting Dashboard..."
    $env:DASH_USER = $DashUser
    $env:DASH_PASS = $DashPass
    $env:DASH_PORT = $DashPort
    try {
        $dashProc = Start-PythonService -WorkingDirectory $DashboardDir -ScriptName "app.py" -StdOutLog $DashboardLog -StdErrLog $DashboardErr
        $dashProc.Id | Set-Content $DashboardPid
        Start-Sleep -Seconds 2

        if (-not $dashProc.HasExited) {
            Write-OK "Dashboard started (PID: $($dashProc.Id))  ->  http://localhost:$DashPort  (login: $DashUser / $DashPass)"
        } else {
            Write-Fail "Dashboard failed to start -- check $DashboardLog and $DashboardErr"
        }
    } catch {
        Write-Fail "Dashboard failed to start -- $($_.Exception.Message)"
    }
}

# --- Stop ---
function Stop-Bots {
    param([switch]$Quiet)

    $services = @(
        @{ Label = "Admin Bot";  PidFile = $AdminBotPid  },
        @{ Label = "VPN Bot";    PidFile = $VpnBotPid    },
        @{ Label = "Enterprise Bot"; PidFile = $EnterpriseBotPid },
        @{ Label = "Dashboard";  PidFile = $DashboardPid }
    )

    foreach ($svc in $services) {
        if (Test-Path $svc.PidFile) {
            $savedPid = Get-Content $svc.PidFile -ErrorAction SilentlyContinue
            if ($savedPid) {
                try {
                    $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
                    if ($proc) {
                        Stop-Process -Id $savedPid -Force -ErrorAction SilentlyContinue
                        if (-not $Quiet) { Write-OK "$($svc.Label) stopped (PID: $savedPid)" }
                    }
                } catch {}
            }
            Remove-Item $svc.PidFile -Force -ErrorAction SilentlyContinue
        }
    }

    if (-not $Quiet) { Write-OK "All services stopped." }
}

# --- Status ---
function Get-BotStatus {
    $allOk = $true
    $services = @(
        @{ Label = "Admin Bot";  PidFile = $AdminBotPid  },
        @{ Label = "VPN Bot";    PidFile = $VpnBotPid    },
        @{ Label = "Enterprise Bot"; PidFile = $EnterpriseBotPid },
        @{ Label = "Dashboard";  PidFile = $DashboardPid }
    )

    foreach ($svc in $services) {
        if (Test-Path $svc.PidFile) {
            $savedPid = Get-Content $svc.PidFile -ErrorAction SilentlyContinue
            $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-OK "$($svc.Label) is RUNNING (PID: $savedPid)"
            } else {
                Write-Fail "$($svc.Label) is NOT running (stale PID: $savedPid)"
                $allOk = $false
            }
        } else {
            Write-Fail "$($svc.Label) is NOT running (no PID file)"
            $allOk = $false
        }
    }

    Write-Host ""
    if ($allOk) { Write-OK "All services are running." }
    else         { Write-Fail "One or more services are not running." }
}

# --- Logs ---
function Show-Logs {
    Write-Info "Tailing logs -- press Ctrl+C to stop"
    Write-Host ""
    Get-Content $AdminBotLog, $VpnBotLog, $EnterpriseBotLog -Wait -Tail 20
}

# --- Help ---
function Show-Help {
    Write-Host ""
    Write-Host "========================================================"
    Write-Host "  Pay If You Like - Dual Bot Manager  (PowerShell)"
    Write-Host "========================================================"
    Write-Host ""
    Write-Host "Usage:  .\run_bots.ps1 [COMMAND]"
    Write-Host ""
    Write-Host "Commands:"
    Write-Host "  start     Start Admin Bot + VPN Bot + Enterprise Bot + Dashboard"
    Write-Host "  stop      Stop all services"
    Write-Host "  restart   Stop then start all services"
    Write-Host "  status    Show running status of all services"
    Write-Host "  logs      Tail both bot logs in real-time"
    Write-Host "  help      Show this help message"
    Write-Host ""
    Write-Host "Log files:"
    Write-Host "  Admin Bot  : $AdminBotLog"
    Write-Host "  Admin Err  : $AdminBotErr"
    Write-Host "  VPN Bot    : $VpnBotLog"
    Write-Host "  VPN Err    : $VpnBotErr"
    Write-Host "  Enterprise : $EnterpriseBotLog"
    Write-Host "  Enterprise : $EnterpriseBotErr"
    Write-Host "  Dashboard  : $DashboardLog"
    Write-Host "  Dashboard  : $DashboardErr"
    Write-Host ""
}

# --- Entry point ---
switch ($Command.ToLower()) {
    "start"   { Start-Bots      }
    "stop"    { Stop-Bots       }
    "restart" { Stop-Bots; Start-Sleep -Seconds 1; Start-Bots }
    "status"  { Get-BotStatus   }
    "logs"    { Show-Logs       }
    default   { Show-Help       }
}
