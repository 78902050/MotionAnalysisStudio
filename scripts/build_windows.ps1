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

$pythonPath = (Get-Command $Python).Source
$pythonDirectory = Split-Path -Parent $pythonPath
$venvRoot = Split-Path -Parent $pythonDirectory
$systemDirectory = Join-Path $env:SystemRoot "System32"
$originalPath = $env:PATH
$env:PATH = @($pythonDirectory, $venvRoot, $systemDirectory, $env:SystemRoot) -join ";"

$arguments = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--distpath", $distPath,
    "--workpath", $workPath,
    (Join-Path $root "MotionAnalysisStudio.spec")
)
try {
    & $pythonPath @arguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    $env:PATH = $originalPath
}

$auditScript = Join-Path $root "scripts\audit_dist_dlls.ps1"
& $auditScript -Dist $distPath -WorkRoot $workPath
$executable = Join-Path $distPath "MotionAnalysisStudio.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "PyInstaller completed without creating $executable"
}
Write-Output $executable
