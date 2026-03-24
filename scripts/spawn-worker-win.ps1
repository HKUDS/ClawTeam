param(
    [Parameter(Mandatory = $true)]
    [string]$Team,
    [Parameter(Mandatory = $true)]
    [string]$AgentName,
    [Parameter(Mandatory = $true)]
    [string]$Task
)

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
python -m clawteam spawn --team $Team --agent-name $AgentName --task $Task windows python
