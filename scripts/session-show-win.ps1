param(
    [Parameter(Mandatory = $true)]
    [string]$Team
)

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
python -m clawteam session show $Team
