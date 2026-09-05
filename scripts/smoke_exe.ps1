param(
    [Alias("Exe")]
    [string]$Executable = "",
    [ValidateSet("Gui", "Workflow", "Capabilities", "All")]
    [string]$Mode = "All"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
if ([string]::IsNullOrWhiteSpace($Executable)) {
    $Executable = Join-Path $root "outputs\build\dist\MotionAnalysisStudio.exe"
}
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Executable not found: $Executable. Run scripts/build_windows.ps1 first."
}

$checks = if ($Mode -eq "All") { @("Gui", "Workflow", "Capabilities") } else { @($Mode) }
foreach ($check in $checks) {
    $argument = switch ($check) {
        "Gui" { "--gui-smoke-test" }
        "Workflow" { "--workflow-smoke-test" }
        default { "--smoke-test" }
    }
    $process = Start-Process -FilePath $Executable -ArgumentList $argument -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "MotionAnalysisStudio.exe $check smoke test failed with exit code $($process.ExitCode)"
    }
    Write-Output "MotionAnalysisStudio.exe $check smoke test passed"
}
