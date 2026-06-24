$ErrorActionPreference = "Stop"

$PackageName = if ($env:LEADS_PACKAGE_NAME) { $env:LEADS_PACKAGE_NAME } else { "leads-cli" }
$SkipInit = $env:LEADS_SKIP_INIT -eq "1"

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    if (Test-Command "py") {
        & py -3 @Arguments
        return
    }
    if (Test-Command "python") {
        & python @Arguments
        return
    }
    if (Test-Command "python3") {
        & python3 @Arguments
        return
    }
    throw "Python 3 is required to install $PackageName."
}

function Invoke-Pipx {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    if (Test-Command "pipx") {
        & pipx @Arguments
        return
    }
    Invoke-Python -m pipx @Arguments
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

Write-Host "Installing $PackageName with pipx..."
if (-not (Test-Command "pipx")) {
    Invoke-Python -m pip install --user pipx
    try {
        Invoke-Python -m pipx ensurepath
    } catch {
        Write-Host "pipx installed. Your shell may need to be restarted for PATH changes."
    }
}

$installed = $false
try {
    $installed = (Invoke-Pipx list --short 2>$null) -contains $PackageName
} catch {
    $installed = $false
}

if ($installed) {
    Invoke-Pipx upgrade $PackageName
} else {
    Invoke-Pipx install $PackageName
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
    Invoke-Pipx run --spec $PackageName leads init
}
