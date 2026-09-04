param(
    [string]$Python = "",
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path

if ([string]::IsNullOrWhiteSpace($Python)) {
    $candidate = Join-Path $root ".venv\Scripts\python.exe"
    $Python = if (Test-Path -LiteralPath $candidate -PathType Leaf) { $candidate } else { "python" }
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $root "outputs\build"
}

$distPath = Join-Path $OutputRoot "dist"
$workPath = Join-Path $OutputRoot "work"
New-Item -ItemType Directory -Force -Path $distPath, $workPath | Out-Null

$arguments = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "MotionAnalysisStudio",
    "--paths", $root,
    "--distpath", $distPath,
    "--workpath", $workPath,
    "--specpath", $workPath,
    (Join-Path $root "app\main.py")
)
& $Python @arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$executable = Join-Path $distPath "MotionAnalysisStudio.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "PyInstaller completed without creating $executable"
}
Write-Output $executable
