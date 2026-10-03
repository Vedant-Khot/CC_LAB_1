param(
  [int]$Requests = 200,
  [string]$Levels = "1,2,4,8,16",
  [int]$StatsIntervalSeconds = 2,
  [int]$SettleSeconds = 3
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$resultsDir = Join-Path $root "results"
New-Item -ItemType Directory -Force -Path $resultsDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$statsFile = Join-Path $resultsDir "docker-stats-$stamp.csv"
$jsonFile = Join-Path $resultsDir "results-$stamp.json"

"timestamp,container,cpu_percent,mem_percent,mem_usage" |
  Out-File -Encoding utf8 $statsFile

Write-Host "Sampling docker stats -> $statsFile"

$statsJob = Start-Job -ScriptBlock {
  param($File, $Interval)
  while ($true) {
    $now = (Get-Date).ToString("HH:mm:ss")
    docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemPerc}},{{.MemUsage}}" 2>$null |
      ForEach-Object { "$now,$($_)" } | Out-File -Append -Encoding utf8 $File
    Start-Sleep -Seconds $Interval
  }
} -ArgumentList $statsFile, $StatsIntervalSeconds

try {
  Write-Host "Waiting ${SettleSeconds}s for containers to settle..."
  Start-Sleep -Seconds $SettleSeconds

  python loadtest\loadtest.py --requests $Requests --levels $Levels --json-out $jsonFile
  if ($LASTEXITCODE -ne 0) { throw "loadtest.py exited with $LASTEXITCODE" }
}
finally {
  Stop-Job $statsJob -ErrorAction SilentlyContinue
  Remove-Job $statsJob -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Peak resource usage per container:"
$rows = Import-Csv $statsFile
$rows | Group-Object container | ForEach-Object {
  $cpu = ($_.Group | ForEach-Object { [double]($_.cpu_percent -replace '[%a-zA-Z]','') } | Measure-Object -Maximum).Maximum
  $memPct = ($_.Group | ForEach-Object { [double]($_.mem_percent -replace '[%a-zA-Z]','') } | Measure-Object -Maximum).Maximum
  $memUsage = ($_.Group | ForEach-Object { $_.mem_usage } | Select-Object -Last 1)
  "{0,-22} peak CPU {1,6}%   peak MEM {2,6}%   last {3}" -f $_.Name, $cpu, $memPct, $memUsage
}

Write-Host ""
Write-Host "Load results: $jsonFile"
Write-Host "Raw stats:    $statsFile"
Write-Host "Evaluation service internal timings:"
try {
  Invoke-RestMethod http://localhost:5003/stats | ConvertTo-Json
} catch {
  Write-Host "could not read evaluation service stats: $_"
}