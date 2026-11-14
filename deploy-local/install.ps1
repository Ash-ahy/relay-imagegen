param(
    [switch]$SkipGui
)

$ErrorActionPreference = "Stop"

$repo = "https://github.com/Ash-ahy/relay-imagegen/archive/refs/heads/main.zip"
$pythonVersion = "3.13.17"
$pythonUrl = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe"
$pythonSha256 = "5DA012101BA2E17113A9A1CD901E9CE1441086F2B7ECB5DE06EC94163899A190"
$skillDir = Join-Path $HOME ".codex\skills\relay-imagegen"
$runtimeDir = Join-Path $skillDir "runtime"
$runtimeExe = Join-Path $runtimeDir "python.exe"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("relay-imagegen-" + [guid]::NewGuid().ToString("N"))
$sourceExtractDir = Join-Path $tempRoot "source"

function Test-PrivatePython {
    if (-not (Test-Path -LiteralPath $runtimeExe)) { return $false }
    $probe = Start-Process -FilePath $runtimeExe -ArgumentList @("-s", "-c", '"import sys, tkinter, pip; raise SystemExit(0 if sys.version_info[:3] == (3, 13, 17) else 1)"') -Wait -PassThru -WindowStyle Hidden
    return ($probe.ExitCode -eq 0)
}

function Find-CompatiblePython {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        (Join-Path $env:ProgramFiles "Python313\python.exe")
    )
    if (${env:ProgramFiles(x86)}) {
        $candidates += Join-Path ${env:ProgramFiles(x86)} "Python313\python.exe"
    }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        $probe = Start-Process -FilePath $candidate -ArgumentList @("-s", "-c", '"import sys, tkinter, pip; raise SystemExit(0 if sys.version_info[:3] == (3, 13, 17) else 1)"') -Wait -PassThru -WindowStyle Hidden
        if ($probe.ExitCode -eq 0) { return $candidate }
    }
    return $null
}

function Ensure-PrivatePython {
    if (Test-PrivatePython) { return }
    if (Test-Path -LiteralPath $runtimeDir) {
        Remove-Item -LiteralPath $runtimeDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

    $compatiblePython = Find-CompatiblePython
    if ($compatiblePython) {
        Write-Host "Found a compatible Python $pythonVersion installation; copying it into the private Skill runtime..."
        New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
        & robocopy (Split-Path -Parent $compatiblePython) $runtimeDir /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
        if ($LASTEXITCODE -gt 7 -or -not (Test-PrivatePython)) {
            throw "Copying the compatible Python runtime failed."
        }
        return
    }

    $installer = Join-Path $tempRoot "python-installer.exe"
    Write-Host "Downloading the private Python $pythonVersion runtime (with Tkinter)..."
    Invoke-WebRequest -Uri $pythonUrl -OutFile $installer
    $actualHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash
    if ($actualHash -ne $pythonSha256) { throw "The Python runtime download failed its SHA256 check." }
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $arguments = @(
        "/quiet", "InstallAllUsers=0", ('TargetDir="{0}"' -f $runtimeDir),
        "Include_launcher=0", "Include_pip=1", "Include_tcltk=1",
        "Include_test=0", "PrependPath=0", "Shortcuts=0"
    )
    $process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Private Python installation failed (exit code $($process.ExitCode))." }
    if (-not (Test-PrivatePython)) { throw "The private Python runtime is missing Tkinter or pip." }
}

try {
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    # When run from a full checkout, install that checkout so local fixes are preserved.
    $localRoot = Split-Path -Parent $PSScriptRoot
    if (Test-Path -LiteralPath (Join-Path $localRoot "scripts\setup.py")) {
        $sourceDir = Get-Item -LiteralPath $localRoot
        Write-Host "Installing from the current project folder..."
    }
    else {
        Write-Host "Downloading Relay Imagegen..."
        $sourceZip = Join-Path $tempRoot "relay-imagegen.zip"
        Invoke-WebRequest -Uri $repo -OutFile $sourceZip
        Expand-Archive -LiteralPath $sourceZip -DestinationPath $sourceExtractDir -Force
        $sourceDir = Get-ChildItem -LiteralPath $sourceExtractDir -Directory | Select-Object -First 1
        if (-not $sourceDir) { throw "The downloaded archive did not contain a project folder." }
    }

    New-Item -ItemType Directory -Path $skillDir -Force | Out-Null
    Get-ChildItem -LiteralPath $sourceDir.FullName -Force |
        Where-Object { $_.Name -notin @("config.json", ".secrets", "runtime") } |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $skillDir $_.Name) -Recurse -Force }

    Ensure-PrivatePython
    Write-Host "Installing image generation dependencies into the private runtime..."
    & $runtimeExe -s -m pip install --upgrade --no-user "openai>=2.37,<3" Pillow certifi
    if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }

    $launcher = Join-Path $skillDir "configure.cmd"
    @(
        "@echo off"
        "setlocal"
        "`"%~dp0runtime\python.exe`" -s `"%~dp0scripts\setup.py`" gui"
        "if errorlevel 1 pause"
    ) | Set-Content -LiteralPath $launcher -Encoding ascii

    if ($SkipGui) {
        Write-Host "Installation complete. Skipping the configuration window."
    }
    else {
        Write-Host "Installation complete. Opening the configuration window..."
        & $runtimeExe -s (Join-Path $skillDir "scripts\setup.py") gui
    }
}
finally {
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
