param(
    [Parameter(Mandatory = $true)]
    [string]$Team,
    [int]$Port = 8080,
    [string]$Host = "127.0.0.1"
)

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
python -m clawteam board serve $Team --host $Host --port $Port
