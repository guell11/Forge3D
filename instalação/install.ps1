<#
  Forge3D installer for Windows.

  Core installation is resumable: every large HTTP asset is first saved as
  *.part and atomically moved into place only after a minimum-size/hash check.
  UltraShape and Blender are optional capabilities; their failures never make
  a validated TRELLIS installation look broken or mark a feature as available.
#>
[CmdletBinding()]
param(
    [AllowEmptyString()]
    [string]$Profile = '',
    [switch]$SkipModels,
    [switch]$SkipEngine,
    [switch]$SkipFrontend,
    [switch]$InstallUltraShape,
    [switch]$AcceptUltraShapeTerms,
    [switch]$InstallBlender,
    [switch]$Repair
)

$ErrorActionPreference = 'Stop'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $ProjectRoot 'runtime'
$RuntimeDir = Join-Path $RuntimeRoot 'trellis'
$ModelsRoot = Join-Path $ProjectRoot 'models\trellis2-gguf'
$DownloadsDir = Join-Path $RuntimeRoot 'downloads'
$InstallLogDir = Join-Path $ProjectRoot 'logs\install'
New-Item -ItemType Directory -Force -Path $RuntimeRoot, $DownloadsDir, $InstallLogDir | Out-Null
$LogFile = Join-Path $InstallLogDir ("install-{0}-{1}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmssfff'), $PID)
# Do not use Start-Transcript on this same file. Windows PowerShell keeps the
# transcript handle exclusive, while this installer intentionally appends
# stdout/stderr from child tools to the log. That race was aborting installs.

function Write-InstallLog {
    param([string]$Level, [string]$Message)
    $line = "{0} [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding utf8
    switch ($Level) {
        'WARN' { Write-Host $line -ForegroundColor Yellow }
        'ERROR' { Write-Host $line -ForegroundColor Red }
        default { Write-Host $line -ForegroundColor Cyan }
    }
}
function Write-Info([string]$Message) { Write-InstallLog 'INFO' $Message }
function Write-Warn([string]$Message) { Write-InstallLog 'WARN' $Message }
function ConvertTo-WindowsCommandLineArgument {
    param([AllowEmptyString()][AllowNull()][string]$Value)
    if ($null -eq $Value -or $Value.Length -eq 0) { return '""' }
    if ($Value -notmatch '[\s"]') { return $Value }

    # Quote according to CommandLineToArgvW rules.  Start-Process on Windows
    # PowerShell receives one argument string, so paths such as "3d engine"
    # must retain their exact boundaries without involving cmd.exe.
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes++
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append((('\' * (($backslashes * 2) + 1)) -join ''))
            [void]$builder.Append('"')
            $backslashes = 0
            continue
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append((('\' * $backslashes) -join ''))
            $backslashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) { [void]$builder.Append((('\' * ($backslashes * 2)) -join '')) }
    [void]$builder.Append('"')
    return $builder.ToString()
}
function Invoke-NativeLogged {
    <#
      Windows PowerShell 5 turns native stderr redirected with `2>&1` into an
      ErrorRecord when ErrorActionPreference is Stop, even if it is redirected
      in the pipeline. trellis-cli prints its normal --help usage to stderr,
      so that behaviour used to abort every install before optional capabilities
      were reached. Start-Process redirects at process level instead; preserve
      both streams in the installer log and use only the native exit code.
    #>
    [OutputType([int], [pscustomobject])]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [switch]$CaptureOutput
    )

    $captureId = [Guid]::NewGuid().ToString('N')
    $stdoutPath = Join-Path $RuntimeRoot "native-$captureId.stdout.log"
    $stderrPath = Join-Path $RuntimeRoot "native-$captureId.stderr.log"
    try {
        $commandLine = (($ArgumentList | ForEach-Object { ConvertTo-WindowsCommandLineArgument ([string]$_) }) -join ' ')
        $process = Start-Process -FilePath $FilePath -ArgumentList $commandLine -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -NoNewWindow -Wait -PassThru
        $exitCode = [int]$process.ExitCode
        $captured = ''
        foreach ($path in @($stdoutPath, $stderrPath)) {
            if (-not (Test-Path -LiteralPath $path)) { continue }
            $text = [System.IO.File]::ReadAllText($path)
            if ($text) {
                $captured += $text
                Add-Content -LiteralPath $LogFile -Value $text.TrimEnd([char[]]"`r`n") -Encoding utf8
            }
        }
        if ($CaptureOutput) {
            return [pscustomobject]@{ ExitCode = $exitCode; Output = $captured }
        }
        return $exitCode
    } finally {
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
}
function Invoke-Required {
    param([string]$Name, [scriptblock]$Action)
    Write-Info $Name
    try { & $Action } catch { Write-InstallLog 'ERROR' "${Name}: $($_.Exception.Message)"; throw }
}
function Invoke-Optional {
    param([string]$Name, [scriptblock]$Action, [System.Collections.IDictionary]$Fallback)
    Write-Info $Name
    try { return & $Action } catch {
        $Fallback.enabled = $false
        $Fallback.available = $false
        $Fallback.detail = $_.Exception.Message
        Write-Warn "$Name não foi concluído: $($_.Exception.Message)"
        return $Fallback
    }
}

function Get-SelectedProfile {
    param([string]$Requested)
    $value = if ([string]::IsNullOrWhiteSpace($Requested)) { '' } else { $Requested.Trim().ToLowerInvariant() }
    if (-not $value) {
        $existing = Join-Path $RuntimeRoot 'engine-profile.json'
        if (Test-Path -LiteralPath $existing) {
            try { $value = [string]((Get-Content -LiteralPath $existing -Raw | ConvertFrom-Json).profile) } catch { }
        }
    }
    if (-not $value) { $value = '8gb' }
    if ($value -notin @('6gb','8gb','12gb','16gb')) { throw "Perfil inválido '$value'. Use 6gb, 8gb, 12gb ou 16gb." }
    return $value
}

$Profile = Get-SelectedProfile $Profile
$Profiles = @{
    '6gb' = [ordered]@{ vram=6; default_quant='q4'; quants=@('q4'); resolution=512; atlas=1024; faces=150000; tiers=@(@{id='balanced';label='Equilibrado';resolution=512;atlas=1024;texture_resolution=1024;quant='q4';description='Q4, geometria 512, atlas 1K e textura PBR 1K.'}); note='Q4 e 512 px para limitar VRAM.' }
    '8gb' = [ordered]@{ vram=8; default_quant='q4'; quants=@('q4'); resolution=512; atlas=1024; faces=150000; tiers=@(@{id='balanced';label='Equilibrado';resolution=512;atlas=1024;texture_resolution=1024;quant='q4';description='Q4, geometria 512, atlas 1K e PBR 1K para RTX 4060 8 GB.'}); note='Q4 e 512 px como perfil seguro inicial.' }
    '12gb' = [ordered]@{ vram=12; default_quant='q4'; quants=@('q4','q8'); resolution=1024; atlas=2048; faces=200000; tiers=@(@{id='balanced';label='Equilibrado';resolution=512;atlas=2048;texture_resolution=1024;quant='q4';description='Q4, geometria 512, atlas 2K e PBR 1K.'},@{id='detailed';label='Detalhado';resolution=1024;atlas=2048;texture_resolution=1024;quant='q8';description='Q8, geometria 1024, atlas 2K e PBR 1K; exige preflight local.'}); note='Q4 e Q8 são baixados; Q4 continua o padrão seguro.' }
    '16gb' = [ordered]@{ vram=16; default_quant='q4'; quants=@('q4','q8'); resolution=1536; atlas=2048; faces=300000; tiers=@(@{id='balanced';label='Equilibrado';resolution=512;atlas=2048;texture_resolution=1024;quant='q4';description='Q4, geometria 512, atlas 2K e PBR 1K.'},@{id='detailed';label='Detalhado';resolution=1024;atlas=2048;texture_resolution=1024;quant='q8';description='Q8, geometria 1024, atlas 2K e PBR 1K.'},@{id='maximum';label='Máximo';resolution=1536;atlas=2048;texture_resolution=1024;quant='q8';description='Q8, geometria 1536, atlas 2K e PBR 1K; experimental e sujeito ao preflight.'}); note='Q4 e Q8 são baixados; Q8 é uma capacidade adicional, não garantia de VRAM.' }
}
$Selected = $Profiles[$Profile]
$ModelFiles = @('birefnet.gguf','dinov3.gguf','ss_flow.gguf','ss_dec.gguf','shape_flow_512.gguf','shape_flow_1024.gguf','shape_dec.gguf','tex_flow_512.gguf','tex_flow_1024.gguf','tex_dec.gguf')

function Invoke-ResumableDownload {
    param([string]$Url, [string]$Destination, [long]$MinimumBytes = 1024, [string]$Sha256 = '')
    if (Test-Path -LiteralPath $Destination) {
        $size = (Get-Item -LiteralPath $Destination).Length
        if ($size -ge $MinimumBytes) {
            if ($Sha256) {
                $actual = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($actual -eq $Sha256.ToLowerInvariant()) { Write-Info "Já verificado: $(Split-Path -Leaf $Destination)"; return }
                Remove-Item -LiteralPath $Destination -Force
            } else { Write-Info "Já existe: $(Split-Path -Leaf $Destination)"; return }
        } else { Remove-Item -LiteralPath $Destination -Force }
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    $part = "$Destination.part"
    Write-Info "Baixando com retomada: $(Split-Path -Leaf $Destination)"
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        $exitCode = Invoke-NativeLogged -FilePath $curl.Source -ArgumentList @('--fail', '--location', '--retry', '4', '--retry-delay', '2', '--continue-at', '-', '--output', $part, $Url)
        if ($exitCode -ne 0) { throw "Download falhou: $(Split-Path -Leaf $Destination). O arquivo .part foi preservado para retomar." }
    } else {
        throw 'curl.exe não encontrado. Ele é necessário para downloads retomáveis; instale/ative o curl do Windows e execute novamente.'
    }
    if (-not (Test-Path -LiteralPath $part) -or (Get-Item -LiteralPath $part).Length -lt $MinimumBytes) { throw "Download incompleto: $part" }
    if ($Sha256) {
        $actual = (Get-FileHash -LiteralPath $part -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $Sha256.ToLowerInvariant()) { throw "Checksum SHA-256 inválido para $(Split-Path -Leaf $Destination)." }
    }
    Move-Item -LiteralPath $part -Destination $Destination -Force
}

function Get-PythonLauncher {
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        & py.exe -3 -c "import sys; assert sys.version_info >= (3,10), sys.version"
        if ($LASTEXITCODE -eq 0) { return @{ command='py.exe'; prefix=@('-3') } }
    }
    if (Get-Command python.exe -ErrorAction SilentlyContinue) {
        & python.exe -c "import sys; assert sys.version_info >= (3,10), sys.version"
        if ($LASTEXITCODE -eq 0) { return @{ command='python.exe'; prefix=@() } }
    }
    throw 'Python 3.10+ não encontrado. Instale Python e marque Add to PATH.'
}
function Get-Python310Launcher {
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        & py.exe -3.10 -c "import sys; assert sys.version_info[:2] == (3,10), sys.version"
        if ($LASTEXITCODE -eq 0) { return @{ command='py.exe'; prefix=@('-3.10') } }
    }
    if (Get-Command python.exe -ErrorAction SilentlyContinue) {
        & python.exe -c "import sys; assert sys.version_info[:2] == (3,10), sys.version"
        if ($LASTEXITCODE -eq 0) { return @{ command='python.exe'; prefix=@() } }
    }
    throw 'UltraShape experimental exige Python 3.10 nativo no Windows.'
}
function Test-ModelSet {
    param([string]$Directory)
    foreach ($name in $ModelFiles) {
        $path = Join-Path $Directory $name
        if (-not (Test-Path -LiteralPath $path) -or (Get-Item -LiteralPath $path).Length -lt 1MB) { throw "Peso GGUF ausente ou incompleto: $path" }
    }
}
function Get-NvidiaAvailable {
    $smi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $smi) { return $false }
    & $smi.Source -L 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Install-BlenderPortable {
    $result = [ordered]@{ requested=$true; enabled=$false; available=$false; version='4.5.12'; executable=''; detail='Não instalado.' }
    $version = '4.5.12'
    $zipName = "blender-$version-windows-x64.zip"
    $zip = Join-Path $DownloadsDir $zipName
    $root = Join-Path $RuntimeRoot "blender\blender-$version-windows-x64"
    $exe = Join-Path $root 'blender.exe'
    Invoke-ResumableDownload "https://download.blender.org/release/Blender4.5/$zipName" $zip 100MB '317ef64e7a2c3cc79ec810c766ae9828aff865bea78039dc695b3f1118c34b4f'
    if (-not (Test-Path -LiteralPath $exe)) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $root) | Out-Null
        Expand-Archive -LiteralPath $zip -DestinationPath (Split-Path -Parent $root) -Force
    }
    if (-not (Test-Path -LiteralPath $exe)) { throw 'Blender portátil foi extraído, mas blender.exe não foi encontrado.' }
    $exitCode = Invoke-NativeLogged -FilePath $exe -ArgumentList @('--background', '--version')
    if ($exitCode -ne 0) { throw 'O preflight do Blender portátil falhou.' }
    $worker = Join-Path $ProjectRoot 'scripts\blender_worker.py'
    $apiPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $worker) -or -not (Test-Path -LiteralPath $apiPython)) { throw 'Worker Blender ou Python da API ausente para a calibração.' }
    $calibration = Join-Path $RuntimeRoot 'blender-calibration'
    New-Item -ItemType Directory -Force -Path $calibration | Out-Null
    $source = Join-Path $calibration 'source.glb'; $output = Join-Path $calibration 'transform.glb'; $parameters = Join-Path $calibration 'parameters.json'
    & $apiPython -c "import sys; sys.path.insert(0,r'$ProjectRoot\backend'); from app.adapters.demo import _cube_glb; open(r'$source','wb').write(_cube_glb())"
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o GLB pequeno de calibração Blender.' }
    [System.IO.File]::WriteAllText($parameters, '{"kind":"transform","transform":{"translation":[0,0,0],"rotation_degrees":[0,0,0],"scale":[1,1,1]}}', (New-Object System.Text.UTF8Encoding($false)))
    Remove-Item -LiteralPath $output -Force -ErrorAction SilentlyContinue
    $exitCode = Invoke-NativeLogged -FilePath $exe -ArgumentList @('--background', '--factory-startup', '--python', $worker, '--', 'transform', '--input', $source, '--output', $output, '--parameters', $parameters)
    if ($exitCode -ne 0 -or -not (Test-Path -LiteralPath $output) -or (Get-Item -LiteralPath $output).Length -lt 20) { throw 'Worker Blender não produziu o GLB de calibração.' }
    if ([System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($output)[0..3]) -ne 'glTF') { throw 'Worker Blender produziu saída sem assinatura GLB.' }
    $result.enabled = $true; $result.available = $true; $result.executable = $exe; $result.detail = 'Blender portátil 4.5 LTS e worker estruturado passaram em uma operação GLB real.'
    return $result
}

function Install-UltraShapeExperimental {
    $result = [ordered]@{ requested=$true; enabled=$false; available=$false; python=''; home=''; checkpoint=''; probe=''; detail='Não instalado.'; mode='experimental' }
    if ($Selected.vram -lt 8) { $result.detail = 'UltraShape não é oferecido no perfil de 6 GB.'; return $result }
    $root = Join-Path $ProjectRoot 'third_party\UltraShape-1.0'
    $venv = Join-Path $ProjectRoot '.venv-ultrashape'
    $python = Join-Path $venv 'Scripts\python.exe'
    $checkpoint = Join-Path $ProjectRoot 'models\ultrashape\ultrashape_v1.pt'
    $worker = Join-Path $ProjectRoot 'scripts\ultrashape_worker.py'
    $probe = Join-Path $RuntimeRoot 'ultrashape-probe.json'
    $result.python=$python; $result.home=$root; $result.checkpoint=$checkpoint; $result.probe=$probe
    if (-not (Get-NvidiaAvailable)) { throw 'GPU NVIDIA/CUDA não detectada; o worker experimental não será instalado.' }
    $git = Get-Command git.exe -ErrorAction SilentlyContinue
    if (-not $git) { throw 'Git não encontrado.' }
    $nvcc = Get-Command nvcc.exe -ErrorAction SilentlyContinue
    if (-not $nvcc) { throw 'CUDA Toolkit 12.1/nvcc não encontrado; o ambiente upstream não será compilado.' }
    $nvccResult = Invoke-NativeLogged -FilePath $nvcc.Source -ArgumentList @('--version') -CaptureOutput
    if ($nvccResult.ExitCode -ne 0) { throw 'Não foi possível consultar a versão do CUDA Toolkit/nvcc.' }
    $nvccVersion = [string]$nvccResult.Output
    if ($nvccVersion -notmatch 'release\s+12\.1(?:\D|$)') {
        $detected = if ($nvccVersion -match 'release\s+([0-9.]+)') { $Matches[1] } else { 'desconhecido' }
        throw "CUDA Toolkit $detected detectado. O UltraShape upstream desta integração exige Toolkit 12.1; CUDA 13 não será tratado como fallback compatível."
    }
    if (-not $AcceptUltraShapeTerms) {
        Write-Warn 'UltraShape é uma integração customizada TRELLIS -> UltraShape. O código upstream inclui termos derivados do Hunyuan; leia docs/RESEARCH.md antes de usar ou redistribuir.'
        $answer = Read-Host 'Digite ACEITO para baixar e testar o UltraShape experimental'
        if ($answer.Trim().ToUpperInvariant() -ne 'ACEITO') { throw 'Termos do UltraShape não confirmados pelo operador.' }
    }
    $launcher = Get-Python310Launcher
    if (-not (Test-Path -LiteralPath (Join-Path $root '.git'))) {
        $exitCode = Invoke-NativeLogged -FilePath $git.Source -ArgumentList @('clone', '--depth', '1', 'https://github.com/PKU-YuanGroup/UltraShape-1.0.git', $root)
        if ($exitCode -ne 0) { throw 'Clone do repositório oficial UltraShape falhou.' }
    }
    if (-not (Test-Path -LiteralPath $python)) {
        & $launcher.command @($launcher.prefix + @('-m','venv',$venv))
        if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o ambiente isolado do UltraShape.' }
    }
    # Upstream pins Torch 2.5.1 + CUDA 12.1. Do not inject CUDA 13 flags,
    # FlashAttention, SDPA monkey patches, or unsupported attention packages.
    & $python -m pip install --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) { throw 'Atualização do pip UltraShape falhou.' }
    & $python -m pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu121
    if ($LASTEXITCODE -ne 0) { throw 'PyTorch 2.5.1/cu121 UltraShape falhou.' }
    Push-Location $root
    try {
        & $python -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Dependências upstream do UltraShape falharam.' }
    } finally { Pop-Location }
    & $python -m pip install 'git+https://github.com/ashawkey/cubvh' --no-build-isolation
    if ($LASTEXITCODE -ne 0) { throw 'cubvh upstream falhou.' }
    # Hash and exact upstream payload size published by infinith/UltraShape.
    # A stale HTML/Xet pointer can therefore never be mistaken for weights.
    Invoke-ResumableDownload 'https://huggingface.co/infinith/UltraShape/resolve/main/ultrashape_v1.pt' $checkpoint 7366231254 'c96ae010c4169597fd0006dcb08056bf6104a1fca249b10fed7ddded324c3f0f'
    if (-not (Test-Path -LiteralPath $worker)) { throw 'Worker estruturado do Forge3D não encontrado.' }
    $exitCode = Invoke-NativeLogged -FilePath $python -ArgumentList @($worker, 'probe', '--source', $root, '--checkpoint', $checkpoint)
    if ($exitCode -ne 0) { throw 'Preflight CUDA/imports UltraShape falhou.' }
    # A real calibration is intentionally not hidden: the separate installer
    # executes it only after the runtime is in place. Failure remains optional.
    $calibrationDir = Join-Path $RuntimeRoot 'ultrashape-calibration'
    New-Item -ItemType Directory -Force -Path $calibrationDir | Out-Null
    $image = Join-Path $calibrationDir 'reference.png'; $mesh = Join-Path $calibrationDir 'coarse.obj'; $glb = Join-Path $calibrationDir 'refined.glb'
    & $python -c "from PIL import Image; Image.new('RGB',(128,128),(100,140,190)).save(r'$image')"
    if ($LASTEXITCODE -ne 0) { throw 'Imagem de calibração UltraShape não pôde ser criada.' }
    [System.IO.File]::WriteAllText($mesh, "v 0 1 0`nv -1 -1 1`nv 1 -1 1`nv 1 -1 -1`nv -1 -1 -1`nf 1 2 3`nf 1 3 4`nf 1 4 5`nf 1 5 2`nf 2 5 4`nf 2 4 3`n", (New-Object System.Text.UTF8Encoding($false)))
    Remove-Item -LiteralPath $glb -Force -ErrorAction SilentlyContinue
    $exitCode = Invoke-NativeLogged -FilePath $python -ArgumentList @($worker, 'refine', '--source', $root, '--checkpoint', $checkpoint, '--image', $image, '--mesh', $mesh, '--output', $glb, '--mode', 'economy', '--seed', '42')
    if ($exitCode -ne 0 -or -not (Test-Path -LiteralPath $glb) -or (Get-Item -LiteralPath $glb).Length -lt 20) { throw 'Calibração real UltraShape falhou; o refinador continuará indisponível.' }
    if ([System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($glb)[0..3]) -ne 'glTF') { throw 'Calibração UltraShape não produziu GLB válido.' }
    $modes = if ($Selected.vram -ge 16) { @('economy','full') } else { @('economy') }
    $probeData = [ordered]@{ passed=$true; generated_at=(Get-Date).ToUniversalTime().ToString('o'); modes=$modes; checkpoint_sha256=(Get-FileHash -LiteralPath $checkpoint -Algorithm SHA256).Hash.ToLowerInvariant(); detail='Preflight e calibração real do UltraShape concluídos.'; calibration_glb=$glb; source='PKU-YuanGroup/UltraShape-1.0'; torch='2.5.1+cu121'; experimental=$true }
    [System.IO.File]::WriteAllText($probe, ($probeData | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding($false)))
    $result.enabled=$true; $result.available=$true; $result.detail=[string]$probeData.detail
    return $result
}

try {
    Write-Info "Forge3D: instalando perfil $Profile. $($Selected.note)"
    if ($Repair) { Write-Info 'Modo de reparo: arquivos finais válidos são preservados; downloads .part serão retomados.' }
    $launcher = Get-PythonLauncher
    $venv = Join-Path $ProjectRoot '.venv'; $python = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { Invoke-Required 'Criando ambiente Python Forge3D' { & $launcher.command @($launcher.prefix + @('-m','venv',$venv)); if ($LASTEXITCODE -ne 0) { throw 'venv falhou.' } } }
    Invoke-Required 'Instalando dependências da API' { & $python -m pip install --upgrade pip; if ($LASTEXITCODE -ne 0) { throw 'pip falhou.' }; & $python -m pip install -r (Join-Path $ProjectRoot 'backend\requirements.txt'); if ($LASTEXITCODE -ne 0) { throw 'requirements da API falharam.' }; & $python -c "import fastapi,uvicorn; print('API_IMPORT_OK')"; if ($LASTEXITCODE -ne 0) { throw 'Preflight de import da API falhou.' } }
    if (-not $SkipFrontend) { Invoke-Required 'Instalando dependências do frontend' { if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Node.js LTS/NPM não encontrado.' }; Push-Location (Join-Path $ProjectRoot 'frontend'); try { & npm.cmd install; if ($LASTEXITCODE -ne 0) { throw 'npm install falhou.' } } finally { Pop-Location } } }

    $serverBin = Join-Path $RuntimeDir 'trellis-server.exe'; $cliBin = Join-Path $RuntimeDir 'trellis-cli.exe'; $modelsDir = Join-Path $ModelsRoot $Selected.default_quant; $serverPort=8091
    if (-not $SkipEngine) {
        Invoke-Required 'Baixando/verificando runtime trellis.cpp' {
            $backend = if (Get-NvidiaAvailable) { 'cuda' } else { 'vulkan' }
            $archive = Join-Path $DownloadsDir "trellis-$backend-windows-x64.zip"
            if (-not (Test-Path -LiteralPath $serverBin) -or -not (Test-Path -LiteralPath $cliBin)) {
                Invoke-ResumableDownload "https://github.com/pwilkin/trellis.cpp/releases/latest/download/trellis-$backend-windows-x64.zip" $archive 1MB
                New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
                Expand-Archive -LiteralPath $archive -DestinationPath $RuntimeDir -Force
            }
            if (-not (Test-Path -LiteralPath $serverBin)) { throw 'trellis-server.exe não foi encontrado após extração.' }
            if (-not (Test-Path -LiteralPath $cliBin)) { throw 'trellis-cli.exe não foi encontrado após extração.' }
        }
        if (-not $SkipModels) {
            foreach ($quant in $Selected.quants) {
                Invoke-Required "Baixando pesos TRELLIS GGUF $quant" {
                    foreach ($model in $ModelFiles) { Invoke-ResumableDownload "https://huggingface.co/ilintar/trellis2-gguf/resolve/main/$quant/$model" (Join-Path (Join-Path $ModelsRoot $quant) $model) 1MB }
                }
            }
        }
    }
    Invoke-Required 'Preflight obrigatório do runtime TRELLIS' {
        if (-not (Test-Path -LiteralPath $serverBin)) { throw 'Runtime TRELLIS ausente.' }
        if (-not (Test-Path -LiteralPath $cliBin)) { throw 'trellis-cli obrigatório ausente.' }
        Test-ModelSet $modelsDir
        $help = Invoke-NativeLogged -FilePath $cliBin -ArgumentList @('--help') -CaptureOutput
        if ($help.ExitCode -ne 0) { throw "Preflight trellis-cli --help falhou (código $($help.ExitCode))." }
    }

    $existingProfile = $null
    $existingProfilePath = Join-Path $RuntimeRoot 'engine-profile.json'
    if (Test-Path -LiteralPath $existingProfilePath) { try { $existingProfile = Get-Content -LiteralPath $existingProfilePath -Raw | ConvertFrom-Json } catch { } }
    $blender = [ordered]@{ requested=[bool]$InstallBlender; enabled=$false; available=$false; version='4.5.12'; executable=''; detail='Não solicitado; a finalização Blender permanece indisponível.' }
    if ($InstallBlender) { $blender = Invoke-Optional 'Instalando Blender portátil 4.5 LTS' { Install-BlenderPortable } $blender }
    elseif ($existingProfile -and $existingProfile.blender.enabled -and (Test-Path -LiteralPath ([string]$existingProfile.blender.executable))) {
        $blender = [ordered]@{ requested=$true; enabled=$true; available=$true; version=[string]$existingProfile.blender.version; executable=[string]$existingProfile.blender.executable; detail='Capability Blender calibrada preservada da instalação anterior.' }
    }
    $ultra = [ordered]@{ requested=[bool]$InstallUltraShape; enabled=$false; available=$false; python=''; home=''; checkpoint=''; probe=''; detail='Não solicitado; execute install-ultrashape-native-experimental.bat para tentar.'; mode='experimental' }
    if ($InstallUltraShape) { $ultra = Invoke-Optional 'Instalando UltraShape experimental' { Install-UltraShapeExperimental } $ultra }
    elseif ($existingProfile -and $existingProfile.ultrashape.enabled -and (Test-Path -LiteralPath ([string]$existingProfile.ultrashape.probe))) {
        $ultra = [ordered]@{ requested=$true; enabled=$true; available=$true; python=[string]$existingProfile.ultrashape.python; home=[string]$existingProfile.ultrashape.home; checkpoint=[string]$existingProfile.ultrashape.checkpoint; probe=[string]$existingProfile.ultrashape.probe; detail='Calibração UltraShape preservada da instalação anterior.'; mode='experimental' }
    }

    # Only now is the profile committed: API/frontend/runtime and TRELLIS model
    # set have passed their required preflight. Optional failures are recorded.
    $profileData = [ordered]@{ schema_version=2; profile=$Profile; generated_at=(Get-Date).ToUniversalTime().ToString('o'); install_log=$LogFile; trellis=[ordered]@{ runtime='trellis.cpp'; model_sets=$Selected.quants; default_quant=$Selected.default_quant; resolution=$Selected.resolution; atlas=$Selected.atlas; face_target=$Selected.faces; server_port=$serverPort; qualities=$Selected.tiers }; ultrashape=$ultra; blender=$blender }
    [System.IO.File]::WriteAllText((Join-Path $RuntimeRoot 'engine-profile.json'), ($profileData | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding($false)))
    $envLines = @('# Gerado pelo instalador Forge3D. Não coloque tokens aqui.', "ENGINE_PROFILE=$Profile", 'ENGINE_MODE=trellis_server', "ENGINE_PROFILE_PATH=$(Join-Path $RuntimeRoot 'engine-profile.json')", "TRELLIS_CLI_BIN=$cliBin", "TRELLIS_CLI_MODELS_DIR=$modelsDir", "TRELLIS_SERVER_URL=http://127.0.0.1:$serverPort", "TRELLIS_SERVER_PORT=$serverPort", "TRELLIS_SERVER_BIN=$serverBin", "TRELLIS_MODELS_DIR=$modelsDir", "TRELLIS_DEFAULT_RESOLUTION=$($Selected.resolution)", "TRELLIS_DEFAULT_ATLAS=$($Selected.atlas)", 'TRELLIS_AUTOSTART=1', "TRELLIS_MANAGED_PID_FILE=$(Join-Path $RuntimeRoot 'trellis-server.pid.json')", "TRELLIS_RELEASE_SCRIPT=$(Join-Path $ProjectRoot 'scripts\release-trellis.ps1')", "ULTRASHAPE_ENABLED=$(if ($ultra.enabled) {'1'} else {'0'})", "ULTRASHAPE_HOME=$($ultra.home)", "ULTRASHAPE_PYTHON=$($ultra.python)", "ULTRASHAPE_CKPT=$($ultra.checkpoint)", "ULTRASHAPE_WORKER=$(Join-Path $ProjectRoot 'scripts\ultrashape_worker.py')", "ULTRASHAPE_PROBE_PATH=$($ultra.probe)", "ULTRASHAPE_INSTALL_STATUS=$($ultra.probe)", "BLENDER_ENABLED=$(if ($blender.enabled) {'1'} else {'0'})", "BLENDER_EXECUTABLE=$($blender.executable)", "BLENDER_VERSION=$($blender.version)", "MESH_OPERATIONS_PYTHON=$($blender.executable)", "MESH_OPERATIONS_WORKER=$(Join-Path $ProjectRoot 'scripts\blender_worker.py')")
    [System.IO.File]::WriteAllText((Join-Path $RuntimeRoot 'engine.env'), ($envLines -join [Environment]::NewLine) + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
    Write-Info "Instalação concluída. Log: $LogFile"
    Write-Host "Execute: $ProjectRoot\run.bat" -ForegroundColor Green
    exit 0
} catch {
    Write-InstallLog 'ERROR' "Instalação interrompida: $($_.Exception.Message)"
    Write-Host "A instalação pode ser retomada: os arquivos .part foram preservados. Log: $LogFile" -ForegroundColor Red
    exit 1
}
