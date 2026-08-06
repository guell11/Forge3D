<# UltraShape is deliberately separate from the base Forge3D installer. #>
[CmdletBinding()]
param(
    [AllowEmptyString()]
    [string]$Profile = '',
    [switch]$AcceptTerms
)

$ErrorActionPreference = 'Stop'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$InstallScript = Join-Path $PSScriptRoot 'install.ps1'
try {
    # Do not splat `-Profile ''`: Windows PowerShell can bind it as an orphan
    # positional argument.  Omitting it intentionally lets install.ps1 reuse
    # the validated current profile, or its safe 8 GB default.
    $baseArguments = @{
        SkipModels = $true
        SkipEngine = $true
        SkipFrontend = $true
        InstallUltraShape = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($Profile)) { $baseArguments.Profile = $Profile.Trim() }
    if ($AcceptTerms) { $baseArguments.AcceptUltraShapeTerms = $true }
    & $InstallScript @baseArguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # UltraShape is optional to the core installer, so install.ps1 correctly
    # remains successful when its native preflight fails.  This dedicated
    # wrapper, however, must only report success when the capability and the
    # real inference probe were actually committed.
    $profilePath = Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime\engine-profile.json'
    if (-not (Test-Path -LiteralPath $profilePath)) { throw 'O perfil final da engine não foi gravado.' }
    $state = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
    $probePath = [string]$state.ultrashape.probe
    $probePassed = $false
    if ($probePath -and (Test-Path -LiteralPath $probePath)) {
        try { $probePassed = (Get-Content -LiteralPath $probePath -Raw | ConvertFrom-Json).passed -eq $true } catch { $probePassed = $false }
    }
    if ($state.ultrashape.enabled -ne $true -or $state.ultrashape.available -ne $true -or -not $probePassed) {
        throw ([string]$state.ultrashape.detail)
    }
    exit 0
} catch {
    # The base installer records UltraShape as unavailable and remains usable;
    # only a missing/invalid base installation should make this wrapper fail.
    Write-Warning "UltraShape experimental não foi habilitado: $($_.Exception.Message)"
    exit 1
}
