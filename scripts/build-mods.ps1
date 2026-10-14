param(
    [Parameter(Mandatory=$true)][string]$GameJar,
    [Parameter(Mandatory=$true)][string]$ModTheSpireJar,
    [Parameter(Mandatory=$true)][string]$BaseModJar,
    [Parameter(Mandatory=$true)][string]$StSLibJar,
    [Parameter(Mandatory=$true)][string]$TogetherInSpireJar,
    [string]$JdkBin = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$jars = @($GameJar, $ModTheSpireJar, $BaseModJar, $StSLibJar, $TogetherInSpireJar)
$resolved = @($jars | ForEach-Object { (Resolve-Path -LiteralPath $_).Path })
$javac = if ($JdkBin) { Join-Path $JdkBin "javac.exe" } else { (Get-Command javac -ErrorAction Stop).Source }
$jar = if ($JdkBin) { Join-Path $JdkBin "jar.exe" } else { (Get-Command jar -ErrorAction Stop).Source }
$classpath = $resolved -join ";"
foreach ($name in @("automp", "testdeck")) {
    $classes = Join-Path $root "build/$name"
    $out = Join-Path $root "out"
    New-Item -ItemType Directory -Force -Path $classes, $out | Out-Null
    $source = if ($name -eq "automp") { Join-Path $root "automp/automp/AutoMP.java" } else { Join-Path $root "testdeck/TestDeck.java" }
    & $javac --release 8 -encoding UTF-8 -cp $classpath -d $classes $source
    if ($LASTEXITCODE -ne 0) { throw "Java compilation failed: $name" }
    Copy-Item -LiteralPath (Join-Path $root "$name/ModTheSpire.json") -Destination $classes
    $output = Join-Path $out "$name.jar"
    & $jar cf $output -C $classes .
    if ($LASTEXITCODE -ne 0) { throw "JAR creation failed: $name" }
    Write-Output "Built $output (own classes and metadata only)"
}
