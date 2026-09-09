param(
    [string]$Dist = "",
    [string]$WorkRoot = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
if ([string]::IsNullOrWhiteSpace($Dist)) {
    $Dist = Join-Path $root "outputs\build\dist"
}
if ([string]::IsNullOrWhiteSpace($WorkRoot)) {
    $WorkRoot = Join-Path $root "outputs\build\work"
}

if (-not (Test-Path -LiteralPath $WorkRoot -PathType Container)) {
    throw "PyInstaller work directory not found: $WorkRoot"
}

$tocFiles = @(Get-ChildItem -LiteralPath $WorkRoot -Recurse -File -Filter "Analysis-00.toc")
if ($tocFiles.Count -eq 0) {
    throw "No PyInstaller Analysis-00.toc found under $WorkRoot"
}

$conflicts = @()
$pattern = "(?is)\('icu(?:uc|in|dt\d*)\.dll'\s*,\s*'[^']*[\\/]poppler[\\/][^']*'"
$tocContents = @()
foreach ($tocFile in $tocFiles) {
    $content = Get-Content -LiteralPath $tocFile.FullName -Raw
    $tocContents += $content
    if ($content -match $pattern) {
        $conflicts += $tocFile.FullName
    }
}

if ($conflicts.Count -gt 0) {
    Write-Error "Bundle analysis selected incompatible Poppler ICU libraries: $($conflicts -join ', ')"
    exit 1
}

$combinedToc = $tocContents -join "`n"
if ($combinedToc -notmatch "(?i)openvino_onnx_frontend\.dll") {
    Write-Error "Bundle is missing required OpenVINO frontend: openvino_onnx_frontend.dll"
    exit 1
}

if ($combinedToc -notmatch "(?i)openvino_intel_cpu_plugin\.dll") {
    Write-Error "Bundle is missing required OpenVINO device plugin: openvino_intel_cpu_plugin.dll"
    exit 1
}

Write-Output "DLL audit passed: no incompatible Poppler ICU libraries were selected; OpenVINO ONNX frontend and CPU plugin are present"
