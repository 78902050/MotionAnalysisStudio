param(
    [string]$Root = "D:\test\data",
    [string]$OutputRoot = "",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
    throw "Real data root not found: $Root"
}
if ([string]::IsNullOrWhiteSpace($Python)) {
    $Python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python executable not found: $Python"
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputRoot = Join-Path $repositoryRoot "outputs\real-data-acceptance\$stamp"
}
if (Test-Path -LiteralPath $OutputRoot) {
    throw "Acceptance output already exists: $OutputRoot"
}

& $Python (Join-Path $repositoryRoot "scripts\real_data_acceptance.py") --root $Root --output $OutputRoot
if ($LASTEXITCODE -ne 0) {
    throw "Real data acceptance failed with exit code $LASTEXITCODE"
}
Write-Output "Real data acceptance passed: $(Join-Path $OutputRoot 'acceptance.json')"
