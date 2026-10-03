param(
  [int]$Requests = 200,
  [int[]]$Levels = @(1, 2, 4, 8, 16),
  [switch]$KeepContainers
)

# Runs workloads W1..W5 (concurrency 1,2,4,8,16) one at a time.
#
# For every workload it writes:
#   results/load_test_outputs/W{n}.txt    raw load tool output (latency, ok/failed counts)
#   results/load_test_outputs/W{n}.json   machine readable version of the same
#   results/docker_stats/W{n}.csv         docker stats samples taken during the workload
#   results/docker_stats/cpu_metrics.csv  exact CPU seconds / peak RSS per container,
#                                         read from each service's /metrics endpoint
#                                         before and after the workload

# docker compose writes progress to stderr, which PowerShell 5.1 turns into error
# records. Stay on Continue and rely on the explicit throw / $LASTEXITCODE checks.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$loadDir = Join-Path $root "results\load_test_outputs"
$statsDir = Join-Path $root "results\docker_stats"

$targets = @(
  @{ name = "registration-service"; url = "http://localhost:5001" },
  @{ name = "opportunity-service"; url = "http://localhost:5002" },
  @{ name = "evaluation-service"; url = "http://localhost:5003" }
)

function Wait-Healthy([string[]]$urls, [int]$timeoutSeconds = 120) {
  $deadline = (Get-Date).AddSeconds($timeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    $allUp = $true
    foreach ($url in $urls) {
      try {
        if ((Invoke-RestMethod -Uri $url -TimeoutSec 3).status -ne "ok") { $allUp = $false }
      }
      catch { $allUp = $false }
    }
    if ($allUp) { return $true }
    Start-Sleep -Seconds 2
  }
  return $false
}

function Get-MetricsSnapshot {
  $snapshot = @{}
  foreach ($target in $targets) {
    try { $snapshot[$target.name] = Invoke-RestMethod -Uri "$($target.url)/metrics" -TimeoutSec 5 }
    catch { $snapshot[$target.name] = $null }
  }
  return $snapshot
}

$healthUrls = $targets | ForEach-Object { "$($_.url)/health" }
Write-Host "waiting for the stack to be up..."
if (-not (Wait-Healthy $healthUrls)) {
  throw "stack is not healthy, run 'docker compose up -d --build' first"
}

# only wipe previous results once the stack is confirmed up
foreach ($dir in @($loadDir, $statsDir)) {
  if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
}
$metricsFile = Join-Path $statsDir "cpu_metrics.csv"
"workload,container,cpu_seconds_before,cpu_seconds_after,cpu_seconds_used,wall_seconds,cpu_percent,memory_peak_mb" |
  Out-File -Encoding utf8 $metricsFile

$workloadIndex = 1
foreach ($level in $Levels) {
  $name = "W$workloadIndex"
  Write-Host ""
  Write-Host "===== $name : concurrency $level, $Requests requests =====" -ForegroundColor Cyan

  if (-not $KeepContainers) {
    # restart all three: cgroup memory.peak is a high-water mark that never
    # resets, so a service that keeps running would report its peak across
    # every earlier workload instead of this one.
    Write-Host "restarting all services so this workload starts clean..."
    docker compose restart 2>&1 | Out-Null
    if (-not (Wait-Healthy $healthUrls)) { throw "$name : services did not become healthy" }
    Start-Sleep -Seconds 3
  }

  $statsFile = Join-Path $statsDir "$name.csv"
  "timestamp,container,cpu_percent,mem_percent,mem_usage" | Out-File -Encoding utf8 $statsFile

  # docker stats samples, one snapshot roughly every 2s (kept as the artefact the
  # manual asks for; the exact numbers come from /metrics below)
  $sampler = Start-Job -ScriptBlock {
    param($File)
    while ($true) {
      $now = (Get-Date).ToString("HH:mm:ss")
      docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemPerc}},{{.MemUsage}}" 2>$null |
        ForEach-Object { "$now,$($_)" } | Out-File -Append -Encoding utf8 $File
    }
  } -ArgumentList $statsFile

  $before = Get-MetricsSnapshot
  $wallStart = Get-Date

  try {
    # Tee-Object would write UTF-16, so buffer it and save as UTF-8 instead
    $output = python loadtest\loadtest.py --requests $Requests --levels $level `
      --json-out (Join-Path $loadDir "$name.json") 2>&1
    $loadExit = $LASTEXITCODE
    $output | Out-File -FilePath (Join-Path $loadDir "$name.txt") -Encoding utf8
    $output | ForEach-Object { Write-Host $_ }
    if ($loadExit -ne 0) { throw "$name : loadtest.py exited with $loadExit" }
  }
  finally {
    Stop-Job $sampler -ErrorAction SilentlyContinue
    Remove-Job $sampler -Force -ErrorAction SilentlyContinue
  }

  $wallSeconds = [math]::Round(((Get-Date) - $wallStart).TotalSeconds, 3)
  $after = Get-MetricsSnapshot

  foreach ($target in $targets) {
    $pre = $before[$target.name]
    $post = $after[$target.name]
    if ($null -eq $pre -or $null -eq $post) {
      Write-Warning "$name : no metrics for $($target.name)"
      continue
    }
    $used = [math]::Round($post.cpu_seconds - $pre.cpu_seconds, 3)
    $cpuPercent = [math]::Round(($used / $wallSeconds) * 100, 2)
    $peakMb = [math]::Round($post.memory_peak_bytes / 1MB, 2)
    Add-Content -Path $metricsFile -Value (
      "{0},{1},{2},{3},{4},{5},{6},{7}" -f $name, $target.name,
      $pre.cpu_seconds, $post.cpu_seconds, $used, $wallSeconds, $cpuPercent, $peakMb)
    Write-Host ("  {0,-22} CPU {1,7}% ({2,6} cpu-s / {3,5} s)   peak RSS {4,7} MB" -f `
      $target.name, $cpuPercent, $used, $wallSeconds, $peakMb)
  }

  $workloadIndex++
}

Write-Host ""
Write-Host "all workloads finished. now build the deliverables:"
Write-Host "  python report\make-table.py     -> results\observation_table.md / .csv"
Write-Host "  python report\make-graphs.py    -> results\graphs\*.png"