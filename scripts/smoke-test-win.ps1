$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$team = "smoke-win"
python -m clawteam team spawn-team $team -d "Windows smoke test" -n leader
python -m clawteam task create $team "smoke task" -o leader
python -m clawteam inbox send $team leader "hello from smoke test"
python -m clawteam inbox receive $team --agent leader
python -m clawteam board show $team
