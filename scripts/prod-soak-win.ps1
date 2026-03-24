param(
    [string]$Team = "prod-soak-win",
    [int]$Cycles = 5
)

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

python -m clawteam team spawn-team $Team -d "Production-style Windows soak" -n leader

for ($i = 1; $i -le $Cycles; $i++) {
    $worker = "worker-$i"
    python -m clawteam spawn --team $Team --agent-name $worker --task "cycle $i worker" windows python
    Start-Sleep -Seconds 1
    python -m clawteam inbox send $Team leader "cycle $i message"
    python -m clawteam inbox receive $Team --agent leader
    python -m clawteam session save $Team --agent leader --session-id "$Team-session-$i"
    $path = "C:\Users\Michael\.clawteam\workspaces\$Team\$worker\cycle-$i.txt"
    python -c "from pathlib import Path; Path(r'$path').write_text('cycle $i\n', encoding='utf-8')"
    python -m clawteam workspace checkpoint $Team $worker -m "checkpoint $i"
    python -m clawteam workspace merge $Team $worker --no-cleanup
}

python -m clawteam team status $Team
