param(
    [Parameter(Mandatory = $true)]
    [string]$Team,
    [Parameter(Mandatory = $true)]
    [string]$Agent,
    [Parameter(Mandatory = $true)]
    [string]$SessionId,
    [string]$LastTask = ""
)

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

if ($LastTask -ne "") {
    python -m clawteam session save $Team --agent $Agent --session-id $SessionId --last-task $LastTask
} else {
    python -m clawteam session save $Team --agent $Agent --session-id $SessionId
}
