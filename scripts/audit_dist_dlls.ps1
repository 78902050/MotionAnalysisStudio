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
foreach ($tocFile in $tocFiles) {
    $content = Get-Content -LiteralPath $tocFile.FullName -Raw
    if ($content -match $pattern) {
        $conflicts += $tocFile.FullName
    }
}

if ($conflicts.Count -gt 0) {
    Write-Error "Bundle analysis selected incompatible Poppler ICU libraries: $($conflicts -join ', ')"
    exit 1
}

Write-Output "DLL audit passed: no incompatible Poppler ICU libraries were selected"
