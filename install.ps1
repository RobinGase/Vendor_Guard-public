# vendor-guard installer -- Windows (Path B, cloud standalone)
#
# Usage (PowerShell):
#   irm https://raw.githubusercontent.com/RobinGase/Vendor_Guard/main/install.ps1 | iex
#   # or, after cloning:
#   .\install.ps1
#
# Env overrides:
#   $env:VENDOR_GUARD_REPO   -- defaults to RobinGase/Vendor_Guard-public on GitHub
#   $env:VENDOR_GUARD_HOME   -- install dir (default: %LOCALAPPDATA%\vendor-guard)
#   $env:ANTHROPIC_API_KEY   -- if set, skips the interactive prompt
#
# Path A (saaf-compliance-shell) requires Linux + KVM and is NOT supported
# on Windows. This installer covers Path B only.

$ErrorActionPreference = 'Stop'

$RepoUrl    = if ($env:VENDOR_GUARD_REPO) { $env:VENDOR_GUARD_REPO } else { 'https://github.com/RobinGase/Vendor_Guard-public.git' }
$InstallDir = if ($env:VENDOR_GUARD_HOME) { $env:VENDOR_GUARD_HOME } else { Join-Path $env:LOCALAPPDATA 'vendor-guard' }
$ConfigDir  = Join-Path $env:APPDATA 'vendor-guard'
$BinDir     = Join-Path $env:LOCALAPPDATA 'Programs\vendor-guard'

function Fail($msg) { Write-Host "error: $msg" -ForegroundColor Red; exit 1 }
function OK($msg)   { Write-Host "[ok] $msg" -ForegroundColor Green }
function Info($msg) { Write-Host $msg }

# 1. Prereqs --------------------------------------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "git is required. Install Git for Windows: https://git-scm.com/download/win"
}

# Find Python 3.11 or 3.12 via the py launcher first (the recommended
# Windows install pattern), falling back to a bare 'python' on PATH.
$Py = $null
$PyArgs = @()
foreach ($v in '3.12','3.11') {
    try {
        $check = & py "-$v" -c "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -eq 0 -and ($check -eq '3.12' -or $check -eq '3.11')) {
            $Py = (Get-Command py).Source
            $PyArgs = @("-$v")
            break
        }
    } catch { }
}
if (-not $Py) {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        try {
            $check = & python -c "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($LASTEXITCODE -eq 0 -and ($check -eq '3.12' -or $check -eq '3.11')) {
                $Py = (Get-Command python).Source
                $PyArgs = @()
            }
        } catch { }
    }
}
if (-not $Py) {
    Fail 'Need Python 3.11 or 3.12 (3.13+ excluded -- NeMo/LangChain compat). Install from https://www.python.org/downloads/ with "Add python.exe to PATH" and the py launcher checked.'
}
OK "Using Python: $Py $($PyArgs -join ' ')"

# 2. Clone or fast-forward ------------------------------------------------
if (Test-Path (Join-Path $InstallDir '.git')) {
    Info "Updating existing checkout at $InstallDir"
    git -C $InstallDir pull --ff-only
} else {
    Info "Cloning into $InstallDir"
    $parent = Split-Path $InstallDir
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    git clone --depth 1 $RepoUrl $InstallDir
}
OK "Source ready"

# 3. Isolated venv + pinned deps ------------------------------------------
Info "Creating venv and installing dependencies"
& $Py @PyArgs -m venv "$InstallDir\.venv"
& "$InstallDir\.venv\Scripts\pip.exe" install --quiet --upgrade pip
& "$InstallDir\.venv\Scripts\pip.exe" install --quiet -r "$InstallDir\requirements.txt"
OK "Dependencies installed"

# 4. API key --------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
$EnvFile = Join-Path $ConfigDir 'env'
if (-not (Test-Path $EnvFile)) {
    $Key = $env:ANTHROPIC_API_KEY
    if (-not $Key) {
        $secure = Read-Host -Prompt 'Anthropic API key (sk-ant-...)' -AsSecureString
        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $Key = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        } finally {
            [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) | Out-Null
        }
    }
    if ([string]::IsNullOrWhiteSpace($Key)) {
        Fail "Empty API key -- aborting."
    }
    # Write as ASCII (no BOM) so the .cmd launcher can parse it cleanly.
    [System.IO.File]::WriteAllText($EnvFile, "ANTHROPIC_API_KEY=$Key`r`n", [System.Text.Encoding]::ASCII)
    OK "API key written to $EnvFile"
} else {
    OK "Existing API key in $EnvFile preserved"
}

# 5. Launcher (.cmd shim) -------------------------------------------------
# We build the .cmd body via a single-quoted here-string (so PowerShell
# leaves @echo, %%A, %* etc. alone) and then string-replace the install
# paths in. Mixing PowerShell variable expansion with cmd-percent syntax
# in an expandable here-string causes PowerShell to parse '@echo' as the
# splatting operator -- avoid it.
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$Launcher = Join-Path $BinDir 'vendor-guard.cmd'
$cmdTemplate = @'
@echo off
setlocal enabledelayedexpansion
for /f "usebackq tokens=1,* delims==" %%A in ("__ENVFILE__") do (
    set "%%A=%%B"
)
"__VENVPY__" "__TUI__" %*
'@
$cmdBody = $cmdTemplate `
    -replace '__ENVFILE__', $EnvFile `
    -replace '__VENVPY__', "$InstallDir\.venv\Scripts\python.exe" `
    -replace '__TUI__',    "$InstallDir\tui.py"
[System.IO.File]::WriteAllText($Launcher, $cmdBody, [System.Text.Encoding]::ASCII)
OK "Launcher written to $Launcher"

# 6. Add to user PATH if missing ------------------------------------------
$userPath = [Environment]::GetEnvironmentVariable('Path','User')
$onPath = $false
if ($userPath) {
    $onPath = ($userPath -split ';' | Where-Object { $_ -and ($_.TrimEnd('\') -ieq $BinDir.TrimEnd('\')) }).Count -gt 0
}
if (-not $onPath) {
    $newPath = if ($userPath) { "$BinDir;$userPath" } else { $BinDir }
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    OK "Added $BinDir to user PATH (open a new terminal to pick it up)"
}

Write-Host ""
Write-Host "Done. Open a new terminal and run:  vendor-guard"
