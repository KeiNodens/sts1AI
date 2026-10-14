param(
    [Parameter(Mandatory=$true)][string]$GameDir,
    [Parameter(Mandatory=$true)][string]$ModTheSpireJar,
    [ValidateSet("host", "join")][string]$Role = "join",
    [int]$Port = 49580,
    [string]$Character = "",
    [switch]$Embark,
    [string]$Mods = "basemod,stslib,spireTogether,CommunicationMod,automp"
)
$ErrorActionPreference = "Stop"
$game = (Resolve-Path -LiteralPath $GameDir).Path
$mts = (Resolve-Path -LiteralPath $ModTheSpireJar).Path
$java = Join-Path $game "jre/bin/javaw.exe"
if (-not (Test-Path -LiteralPath $java)) { throw "Game Java runtime not found: jre/bin/javaw.exe" }
$env:TIS_AUTOMP = $Role
$env:TIS_PORT = "$Port"
$env:TIS_HOST_IP = "127.0.0.1"
$env:TIS_ASC = "0"
$env:TIS_CHAR = $Character
$env:TIS_EMBARK = if ($Embark) { "1" } else { "0" }
$env:STS1_BRIDGE_PORT = if ($Role -eq "host") { "15532" } else { "15531" }
Start-Process -FilePath $java -ArgumentList @("-jar", "`"$mts`"", "--mods", $Mods, "--skip-intro") -WorkingDirectory $game
