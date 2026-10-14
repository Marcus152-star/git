$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$version = "0.4.1"
$packageName = "GenFollower-Inquiry-Router-$version-windows-x64"
$buildRoot = Join-Path $repoRoot "build\pyinstaller"
$releaseRoot = Join-Path $repoRoot "release"
$packageRoot = Join-Path $releaseRoot $packageName
$zipPath = Join-Path $releaseRoot "$packageName.zip"
$localConfig = Join-Path $repoRoot "config.local.json"
$existingPackageConfig = Join-Path $packageRoot "config.local.json"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing virtual environment: $python"
}

if ((Test-Path -LiteralPath $existingPackageConfig) -and -not (Test-Path -LiteralPath $localConfig)) {
    Copy-Item -LiteralPath $existingPackageConfig -Destination $localConfig
}

foreach ($path in @($buildRoot, $packageRoot, $zipPath)) {
    $fullPath = [System.IO.Path]::GetFullPath($path)
    if (-not $fullPath.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the repository: $fullPath"
    }
    if (Test-Path -LiteralPath $fullPath) {
        Remove-Item -LiteralPath $fullPath -Recurse -Force
    }
}

New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name "inquiry-router" `
    --paths (Join-Path $repoRoot "src") `
    --distpath $packageRoot `
    --workpath (Join-Path $buildRoot "work") `
    --specpath $buildRoot `
    (Join-Path $repoRoot "packaging\entrypoint.py")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "GenFollower-Inquiry-Router-GUI" `
    --paths (Join-Path $repoRoot "src") `
    --distpath $packageRoot `
    --workpath (Join-Path $buildRoot "gui-work") `
    --specpath $buildRoot `
    (Join-Path $repoRoot "packaging\gui_entrypoint.py")

if ($LASTEXITCODE -ne 0) {
    throw "GUI PyInstaller build failed with exit code $LASTEXITCODE"
}

Copy-Item -LiteralPath (Join-Path $repoRoot "config.example.json") -Destination (Join-Path $packageRoot "config.local.json")
Copy-Item -LiteralPath (Join-Path $repoRoot "packaging\README-CN.txt") -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $repoRoot "examples") -Destination $packageRoot -Recurse
New-Item -ItemType Directory -Path (Join-Path $packageRoot "data") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $packageRoot "reports") -Force | Out-Null

$archiveCreated = $false
for ($attempt = 1; $attempt -le 5; $attempt++) {
    try {
        if (Test-Path -LiteralPath $zipPath) {
            Remove-Item -LiteralPath $zipPath -Force
        }
        Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipPath -CompressionLevel Optimal
        $archiveCreated = $true
        break
    }
    catch {
        if ($attempt -eq 5) {
            throw
        }
        Start-Sleep -Seconds 2
    }
}

if (-not $archiveCreated) {
    throw "Portable ZIP was not created"
}

# Keep the distributable ZIP free of real addresses, while restoring the developer's
# ignored local configuration into the runnable release directory after compression.
if (Test-Path -LiteralPath $localConfig) {
    Copy-Item -LiteralPath $localConfig -Destination (Join-Path $packageRoot "config.local.json") -Force
}

Write-Host "Created: $zipPath"
