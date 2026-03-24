param(
    [string]$Team = "soak-win",
    [int]$Iterations = 10
)

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

python -m clawteam team spawn-team $Team -d "Windows soak test" -n leader

for ($i = 1; $i -le $Iterations; $i++) {
    python -m clawteam task create $Team "soak task $i" -o leader
    python -m clawteam inbox send $Team leader "soak message $i"
    python -m clawteam inbox receive $Team --agent leader
    python -m clawteam session save $Team --agent leader --session-id "soak-$i"
    python -m clawteam cost report $Team --agent leader --input-tokens 100 --output-tokens 20 --cost-cents 5 --model soak-model --provider local
}

python -m clawteam board show $Team
