param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
& $Python -m unittest discover -s tests -q
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
