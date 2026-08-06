[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PidFile,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedBin
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $PidFile)) { exit 0 }
try {
    $record = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
    $pidValue = [int]$record.pid
    if ($pidValue -le 0) { throw 'PID inválido no registro gerenciado.' }
    $expectedPath = [System.IO.Path]::GetFullPath($ExpectedBin)
    $recordedPath = [System.IO.Path]::GetFullPath([string]$record.expected_bin)
    if (-not $expectedPath.Equals($recordedPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'O registro pertence a outro executável; a engine não encerrará esse processo.'
    }
    $process = Get-Process -Id $pidValue -ErrorAction Stop
    if (-not $process.Path) { throw 'Não foi possível confirmar o caminho do processo TRELLIS gerenciado.' }
    $actualPath = [System.IO.Path]::GetFullPath($process.Path)
    if (-not $actualPath.Equals($expectedPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "PID $pidValue não corresponde ao executável TRELLIS registrado; nenhuma ação foi tomada."
    }
    Stop-Process -Id $pidValue -ErrorAction Stop
    Wait-Process -Id $pidValue -Timeout 20 -ErrorAction SilentlyContinue
    if (Get-Process -Id $pidValue -ErrorAction SilentlyContinue) { throw 'O processo TRELLIS não terminou dentro de 20 segundos.' }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Write-Output 'TRELLIS_RELEASED:managed process stopped'
} catch {
    Write-Error "TRELLIS_RELEASE_FAILED: $($_.Exception.Message)"
    exit 2
}
