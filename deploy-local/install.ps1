$ErrorActionPreference = "Stop"

$repo = "https://github.com/Ash-ahy/relay-imagegen/archive/refs/heads/main.zip"
$skillDir = Join-Path $HOME ".codex\skills\relay-imagegen"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("relay-imagegen-" + [guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tempRoot "relay-imagegen.zip"
$extractDir = Join-Path $tempRoot "src"

try {
    # When run from a full checkout, install that checkout so local fixes are preserved.
    $localRoot = Split-Path -Parent $PSScriptRoot
    if (Test-Path -LiteralPath (Join-Path $localRoot "scripts\setup.py")) {
        $sourceDir = Get-Item -LiteralPath $localRoot
        Write-Host "Installing from the current project folder..."
    }
    else {
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
        Write-Host "Downloading Relay Imagegen..."
        Invoke-WebRequest -Uri $repo -OutFile $zipPath
        Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force
        $sourceDir = Get-ChildItem -LiteralPath $extractDir -Directory | Select-Object -First 1
        if (-not $sourceDir) { throw "The downloaded archive did not contain a project folder." }
    }

    New-Item -ItemType Directory -Path $skillDir -Force | Out-Null
    Get-ChildItem -LiteralPath $sourceDir.FullName -Force | Where-Object { $_.Name -notin @("config.json", ".secrets") } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $skillDir $_.Name) -Recurse -Force
    }

    Write-Host "Installing Python dependencies..."
    py -3.13 -m pip install --user --upgrade openai Pillow certifi
    Write-Host "Installation complete. Opening the configuration window..."
    & py -3.13 (Join-Path $skillDir "scripts\setup.py") gui
}
finally {
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
