param(
    [string]$Executable = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
if ([string]::IsNullOrWhiteSpace($Executable)) {
    $Executable = Join-Path $root "outputs\build\dist\MotionAnalysisStudio.exe"
}
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Executable not found: $Executable. Run scripts/build_windows.ps1 first."
}

$process = Start-Process -FilePath $Executable -ArgumentList "--smoke-test" -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -ne 0) {
    throw "MotionAnalysisStudio.exe smoke test failed with exit code $($process.ExitCode)"
}
Write-Output "MotionAnalysisStudio.exe smoke test passed"
