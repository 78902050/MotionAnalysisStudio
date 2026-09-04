param(
    [string]$Destination = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
if ([string]::IsNullOrWhiteSpace($Destination)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $Destination = Join-Path (Split-Path $root -Parent) "motion-analysis-studio-$stamp.zip"
}

$paths = @(
    "app",
    "docs",
    "scripts",
    "tests",
    "AGENTS.md",
    ".gitignore",
    "pyproject.toml"
)
$existing = $paths |
    ForEach-Object { Join-Path $root $_ } |
    Where-Object { Test-Path $_ }

if (-not $existing) {
    throw "No project files were found to archive."
}

Compress-Archive -Path $existing -DestinationPath $Destination -Force
Write-Output $Destination
