param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
python -m clawteam @Args
