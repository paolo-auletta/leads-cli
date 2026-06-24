$ErrorActionPreference = "Stop"

$PackageName = if ($env:LEADS_PACKAGE_NAME) { $env:LEADS_PACKAGE_NAME } else { "leads-cli" }
$SkipInit = $env:LEADS_SKIP_INIT -eq "1"
$LeadsPythonVersion = if ($env:LEADS_PYTHON_VERSION) { $env:LEADS_PYTHON_VERSION } else { "3.13" }
$LeadsPythonExe = $null

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-WindowsArm64 {
    return ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") -or ($env:PROCESSOR_ARCHITEW6432 -eq "ARM64")
}

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    if ($script:LeadsPythonExe) {
        & $script:LeadsPythonExe @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Python command failed: $script:LeadsPythonExe $($Arguments -join ' ')"
        }
        return
    }
    if (Test-Command "py") {
        & py -3 @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Python command failed: py -3 $($Arguments -join ' ')"
        }
        return
    }
    if (Test-Command "python") {
        & python @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Python command failed: python $($Arguments -join ' ')"
        }
        return
    }
    if (Test-Command "python3") {
        & python3 @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Python command failed: python3 $($Arguments -join ' ')"
        }
        return
    }
    throw "Python 3 is required to install $PackageName."
}

function Invoke-Pipx {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    if (Test-Command "pipx") {
        & pipx @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "pipx command failed: pipx $($Arguments -join ' ')"
        }
        return
    }
    Invoke-Python -m pipx @Arguments
}

function Invoke-NativeQuiet {
    param(
        [string]$Command,
        [string[]]$Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $Command @Arguments 2>&1
        return @{
            ExitCode = $LASTEXITCODE
            Output = $output
        }
    } catch {
        return @{
            ExitCode = 1
            Output = $null
        }
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Get-PythonExecutable {
    param([string]$Version)

    $probe = "import sys; print(sys.executable)"
    $compactVersion = $Version -replace "\.", ""
    $candidates = @(
        @{ Command = "py"; Arguments = @("-$Version", "-c", $probe) },
        @{ Command = "python$Version"; Arguments = @("-c", $probe) },
        @{ Command = "python3"; Arguments = @("-c", "import sys; ok = sys.version_info[:2] == tuple(map(int, '$Version'.split('.'))); print(sys.executable) if ok else None; raise SystemExit(0 if ok else 1)") },
        @{ Command = "python"; Arguments = @("-c", "import sys; ok = sys.version_info[:2] == tuple(map(int, '$Version'.split('.'))); print(sys.executable) if ok else None; raise SystemExit(0 if ok else 1)") }
    )

    foreach ($candidate in $candidates) {
        if (-not (Test-Command $candidate.Command)) {
            continue
        }
        $result = Invoke-NativeQuiet $candidate.Command $candidate.Arguments
        if ($result.ExitCode -eq 0 -and $result.Output) {
            return ($result.Output | Where-Object { $_ -is [string] -and $_ } | Select-Object -Last 1)
        }
    }

    $pathCandidates = @()
    if ($env:LOCALAPPDATA) {
        $pathCandidates += Join-Path $env:LOCALAPPDATA "Programs\Python\Python$compactVersion\python.exe"
    }
    if ($env:ProgramFiles) {
        $pathCandidates += Join-Path $env:ProgramFiles "Python$compactVersion\python.exe"
    }

    foreach ($path in $pathCandidates) {
        if (-not (Test-Path $path)) {
            continue
        }
        $result = Invoke-NativeQuiet $path @("-c", $probe)
        if ($result.ExitCode -eq 0 -and $result.Output) {
            return ($result.Output | Where-Object { $_ -is [string] -and $_ } | Select-Object -Last 1)
        }
    }

    return $null
}

function Install-LeadsPython {
    param([string]$Version)

    if (-not (Test-Command "winget")) {
        throw "Python $Version is required for Leads, and this installer cannot install it because winget is unavailable. Install Python $Version, then rerun this installer."
    }

    Write-Host "Python $Version was not found. Installing Python $Version with winget..."
    & winget install --id "Python.Python.$Version" --exact --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget could not install Python $Version. Install Python $Version, then rerun this installer."
    }

    $python = Get-PythonExecutable $Version
    if (-not $python) {
        throw "Python $Version was installed, but this shell cannot find it yet. Open a new PowerShell window and rerun this installer."
    }
    return $python
}

function Get-PipxPythonArgs {
    if (-not $script:LeadsPythonExe) {
        $script:LeadsPythonExe = Get-PythonExecutable $LeadsPythonVersion
    }

    if (-not $script:LeadsPythonExe -and (Test-WindowsArm64)) {
        $script:LeadsPythonExe = Install-LeadsPython $LeadsPythonVersion
    }

    $python = if ($script:LeadsPythonExe) { $script:LeadsPythonExe } else { $LeadsPythonVersion }
    $args = @("--python", $python)
    try {
        $help = (Invoke-Pipx install --help 2>&1) -join "`n"
        if ($help -match "--fetch-python" -and -not (Test-WindowsArm64)) {
            $args += @("--fetch-python", "missing")
        }
    } catch {
        # Older pipx versions may not expose help cleanly here; --python is still the important part.
    }
    return $args
}

function Find-Leads {
    $command = Get-Command "leads" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $local = Join-Path $HOME ".local\bin\leads.exe"
    if (Test-Path $local) {
        return $local
    }
    return $null
}

Write-Host "Installing $PackageName with pipx using Python $LeadsPythonVersion..."
if (Test-WindowsArm64) {
    $script:LeadsPythonExe = Get-PythonExecutable $LeadsPythonVersion
    if (-not $script:LeadsPythonExe) {
        $script:LeadsPythonExe = Install-LeadsPython $LeadsPythonVersion
    }
} elseif (-not (Test-Command "py") -and -not (Test-Command "python") -and -not (Test-Command "python3")) {
    $script:LeadsPythonExe = Install-LeadsPython $LeadsPythonVersion
}

if (-not (Test-Command "pipx")) {
    Invoke-Python -m pip install --user pipx
    try {
        Invoke-Python -m pipx ensurepath
    } catch {
        Write-Host "pipx installed. Your shell may need to be restarted for PATH changes."
    }
}

$PipxPythonArgs = Get-PipxPythonArgs

$installed = $false
try {
    $installed = (Invoke-Pipx list --short 2>$null) -contains $PackageName
} catch {
    $installed = $false
}

if ($installed) {
    $reinstallArgs = @("reinstall") + $PipxPythonArgs + @($PackageName)
    Invoke-Pipx @reinstallArgs
} else {
    $installArgs = @("install") + $PipxPythonArgs + @($PackageName)
    Invoke-Pipx @installArgs
}

if ($SkipInit) {
    Write-Host "Installed $PackageName. Run 'leads init' when you are ready."
    exit 0
}

$leads = Find-Leads
if ($leads) {
    & $leads init
} else {
    Write-Host "Could not find 'leads' on PATH yet; running the package through pipx once."
    $runArgs = @("run") + $PipxPythonArgs + @("--spec", $PackageName, "leads", "init")
    Invoke-Pipx @runArgs
}
