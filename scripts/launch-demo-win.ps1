param(
    [string]$Team = "demo-win"
)

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

python -m clawteam team spawn-team $Team -d "Windows demo team" -n leader
python -m clawteam board serve $Team --host 127.0.0.1 --port 8080
