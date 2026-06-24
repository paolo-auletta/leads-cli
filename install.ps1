$ErrorActionPreference = "Stop"

$PackageName = if ($env:LEADS_PACKAGE_NAME) { $env:LEADS_PACKAGE_NAME } else { "leads-cli" }
$SkipInit = $env:LEADS_SKIP_INIT -eq "1"
$LeadsPythonVersion = if ($env:LEADS_PYTHON_VERSION) { $env:LEADS_PYTHON_VERSION } else { "3.13" }

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
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

function Get-PipxPythonArgs {
    $args = @("--python", $LeadsPythonVersion)
    try {
        $help = (Invoke-Pipx install --help 2>&1) -join "`n"
        if ($help -match "--fetch-python") {
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
