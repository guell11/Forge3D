[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$Restart
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot 'logs'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

function Test-TcpPort {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(500, $false)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Wait-ForPort {
    param([int]$Port, [int]$Seconds = 30)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpPort -Port $Port) { return $true }
        Start-Sleep -Milliseconds 400
    }
    return $false
}

function Stop-Forge3DPort {
    param([int]$Port)
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $pidValue = [int]$listener.OwningProcess
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $pidValue" -ErrorAction SilentlyContinue
        $commandLine = [string]$processInfo.CommandLine
        $belongsToForge3D = $commandLine -and $commandLine.IndexOf($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        if (-not $belongsToForge3D -and $Port -eq 8000) {
            try {
                $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
                $belongsToForge3D = $health.service -in @('Forge3D Local API', 'Local 3D Engine API')
            } catch { $belongsToForge3D = $false }
        }
        if (-not $belongsToForge3D) {
            Write-Warning "A porta $Port está em uso por um processo que não pertence ao Forge3D; ele não será encerrado."
            continue
        }
        Stop-Process -Id $pidValue -ErrorAction Stop
        $deadline = (Get-Date).AddSeconds(10)
        while ((Get-Date) -lt $deadline -and (Test-TcpPort -Port $Port)) { Start-Sleep -Milliseconds 200 }
    }
}

function Import-EngineEnvironment {
    $envFile = Join-Path $ProjectRoot 'runtime\engine.env'
    if (-not (Test-Path -LiteralPath $envFile)) { return }
    foreach ($line in Get-Content -LiteralPath $envFile) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#') -or -not $trimmed.Contains('=')) { continue }
        $name, $value = $trimmed.Split('=', 2)
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), 'Process')
    }
}

Import-EngineEnvironment

if ($Restart) {
    Stop-Forge3DPort -Port 8000
    Stop-Forge3DPort -Port 5173
}

$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Ambiente Python não encontrado. Execute primeiro um instalador em 'instalação'."
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Node.js/NPM não encontrado. Instale o Node.js LTS e execute novamente o instalador.'
}

$BackendPort = 8000
$FrontendPort = 5173
$TrellisPort = if ($env:TRELLIS_SERVER_PORT) { [int]$env:TRELLIS_SERVER_PORT } else { 8091 }
$StartTrellis = $env:TRELLIS_AUTOSTART -in @('1', 'true', 'yes', 'on')
$TrellisResolution = if ($env:TRELLIS_DEFAULT_RESOLUTION) { [int]$env:TRELLIS_DEFAULT_RESOLUTION } else { 512 }
$TrellisAtlas = if ($env:TRELLIS_DEFAULT_ATLAS) { [int]$env:TRELLIS_DEFAULT_ATLAS } else { 1024 }
$TrellisPidFile = if ($env:TRELLIS_MANAGED_PID_FILE) { $env:TRELLIS_MANAGED_PID_FILE } else { Join-Path $ProjectRoot 'runtime\trellis-server.pid.json' }

# The C++ server is optional: the API still starts and exposes a clear unavailable state.
$ServerBin = $env:TRELLIS_SERVER_BIN
$ModelsDir = $env:TRELLIS_MODELS_DIR
if ($StartTrellis -and $ServerBin -and $ModelsDir -and (Test-Path -LiteralPath $ServerBin) -and (Test-Path -LiteralPath $ModelsDir) -and -not (Test-TcpPort -Port $TrellisPort)) {
    $serverArgs = "--models `"$ModelsDir`" --port $TrellisPort --res $TrellisResolution --atlas $TrellisAtlas"
    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $trellisProcess = Start-Process -FilePath $ServerBin -ArgumentList $serverArgs -WorkingDirectory (Split-Path -Parent $ServerBin) -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $LogDir "trellis-$timestamp.out.log") `
        -RedirectStandardError (Join-Path $LogDir "trellis-$timestamp.err.log")
    if (Wait-ForPort -Port $TrellisPort -Seconds 10) {
        $managedRecord = [ordered]@{ pid = $trellisProcess.Id; expected_bin = [System.IO.Path]::GetFullPath($ServerBin); started_at = (Get-Date).ToUniversalTime().ToString('o') }
        [System.IO.File]::WriteAllText($TrellisPidFile, ($managedRecord | ConvertTo-Json -Compress), (New-Object System.Text.UTF8Encoding($false)))
    } else {
        Write-Warning 'O servidor TRELLIS não respondeu; nenhum PID foi registrado para liberação segura de VRAM.'
    }
}

if (-not (Test-TcpPort -Port $BackendPort)) {
    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Start-Process -FilePath $Python -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$BackendPort" `
        -WorkingDirectory (Join-Path $ProjectRoot 'backend') -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir "api-$timestamp.out.log") `
        -RedirectStandardError (Join-Path $LogDir "api-$timestamp.err.log")
    if (-not (Wait-ForPort -Port $BackendPort -Seconds 30)) {
        throw "A API não iniciou. Consulte os logs em '$LogDir'."
    }
}

if (-not (Test-TcpPort -Port $FrontendPort)) {
    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm.cmd run dev -- --host 127.0.0.1 --port 5173' `
        -WorkingDirectory (Join-Path $ProjectRoot 'frontend') -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir "ui-$timestamp.out.log") `
        -RedirectStandardError (Join-Path $LogDir "ui-$timestamp.err.log")
    if (-not (Wait-ForPort -Port $FrontendPort -Seconds 45)) {
        throw "A interface não iniciou. Consulte os logs em '$LogDir'."
    }
}

$Url = "http://127.0.0.1:$FrontendPort"
Write-Host "Engine 3D pronta em $Url" -ForegroundColor Green
if (-not $NoBrowser) { Start-Process $Url }
