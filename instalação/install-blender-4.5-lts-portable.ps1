[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$installScript = Join-Path $PSScriptRoot 'install.ps1'
try {
    & $installScript -InstallBlender -SkipModels -SkipEngine -SkipFrontend
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $profilePath = Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime\engine-profile.json'
    if (-not (Test-Path -LiteralPath $profilePath)) { throw 'O perfil final da engine não foi gravado.' }
    $state = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
    $executable = [string]$state.blender.executable
    if ($state.blender.enabled -ne $true -or $state.blender.available -ne $true -or -not (Test-Path -LiteralPath $executable)) {
        throw ([string]$state.blender.detail)
    }
    exit 0
} catch {
    Write-Warning "Blender/worker não foi habilitado: $($_.Exception.Message)"
    exit 1
}
