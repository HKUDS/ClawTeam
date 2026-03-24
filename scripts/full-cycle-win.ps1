param(
    [string]$Team = "prod-win",
    [int]$Port = 8080
)

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

python -m clawteam team spawn-team $Team -d "Windows production cycle" -n leader
python -m clawteam task create $Team "initial coordination task" -o leader
python -m clawteam session save $Team --agent leader --session-id "$Team-session-001"
python -m clawteam board serve $Team --host 127.0.0.1 --port $Port
