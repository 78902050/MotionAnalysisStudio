param(
    [Parameter(Mandatory = $true)]
    [string]$Root,
    [Parameter(Mandatory = $true)]
    [string]$Output
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
    throw "Test data root not found: $Root"
}

$resolvedRoot = (Resolve-Path -LiteralPath $Root).Path.TrimEnd("\")
$relativePrefix = $resolvedRoot + "\"
$files = @(
    Get-ChildItem -LiteralPath $resolvedRoot -Recurse -File |
        Sort-Object FullName |
        ForEach-Object {
            $file = $_
            $relativePath = $file.FullName.Substring($relativePrefix.Length).Replace("\", "/")
            $extension = $file.Extension.ToLowerInvariant()
            $format = switch ($extension) {
                ".toml" {
                    if ($file.Name -like "camera_array*.toml") { "calibration_toml" } else { "toml" }
                }
                ".json" {
                    if ($file.Directory.Name -like "*_json" -and $file.BaseName -match "_\d+$") {
                        "pose2d_json"
                    }
                    else {
                        "json"
                    }
                }
                ".trc" { "pose3d_trc" }
                ".mp4" { "video" }
                ".c3d" { "c3d" }
                ".mot" { "opensim_motion" }
                ".osim" { "opensim_model" }
                ".sto" { "opensim_storage" }
                default { "other" }
            }
            [ordered]@{
                relative_path = $relativePath
                extension = $extension
                size = [long]$file.Length
                format = $format
            }
        }
)

$extensionCounts = @(
    $files |
        Group-Object extension |
        Sort-Object Name |
        ForEach-Object {
            [ordered]@{ extension = $_.Name; count = $_.Count }
        }
)
$payload = [ordered]@{
    schema_version = 1
    file_count = $files.Count
    extension_counts = $extensionCounts
    files = $files
}

$outputPath = [System.IO.Path]::GetFullPath($Output)
$outputDirectory = Split-Path -Parent $outputPath
if (-not [string]::IsNullOrWhiteSpace($outputDirectory)) {
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
}
$payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $outputPath -Encoding UTF8
Write-Output $outputPath
