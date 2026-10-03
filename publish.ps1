param(
  [string]$ImagePrefix = $env:IMAGE_PREFIX,
  [string]$ImageTag = $env:IMAGE_TAG
)

# Builds the three service images and pushes them to Docker Hub.
#
#   powershell -ExecutionPolicy Bypass -File publish.ps1 -ImagePrefix <yourhubusername>
#
# Log in first:  docker login     (nothing is stored in this repository)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# pick up IMAGE_PREFIX / IMAGE_TAG from .env if it exists
$envFile = Join-Path $root ".env"
if ((Test-Path $envFile) -and -not $ImagePrefix) {
  Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([^#=\s]+)\s*=\s*(.*)\s*$') {
      [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
    }
  }
  if (-not $ImagePrefix) { $ImagePrefix = $env:IMAGE_PREFIX }
  if (-not $ImageTag) { $ImageTag = $env:IMAGE_TAG }
}
if (-not $ImageTag) { $ImageTag = "latest" }

$services = @("registration-service", "opportunity-service", "evaluation-service")

docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Error "docker engine is not reachable - start Docker Desktop and retry"
  exit 1
}

if (-not $ImagePrefix -or $ImagePrefix -eq "yourhubusername") {
  Write-Error "pass your Docker Hub username, e.g."
  Write-Error "  powershell -ExecutionPolicy Bypass -File publish.ps1 -ImagePrefix <yourhubusername>"
  exit 1
}

Write-Host "pushing as docker.io/$ImagePrefix/<service>:$ImageTag"
Write-Host ""

$dockerConfig = if ($env:DOCKER_CONFIG) { $env:DOCKER_CONFIG } else { "$HOME\.docker" }
if (-not (Select-String -Path "$dockerConfig\config.json" -Pattern 'docker.io' -Quiet -ErrorAction SilentlyContinue)) {
  Write-Warning "no docker.io credentials found - run 'docker login' first"
}

Write-Host "building..."
docker compose build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "pushing..."
foreach ($service in $services) {
  $tag = "$ImagePrefix/${service}:$ImageTag"
  Write-Host "-> $tag"
  docker push $tag
  if ($LASTEXITCODE -ne 0) {
    Write-Error "push failed for $tag - if this says 'unauthorized', run 'docker login' first"
    exit $LASTEXITCODE
  }
}

Write-Host ""
Write-Host "local images:"
docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}' | Select-String $ImagePrefix

Write-Host ""
Write-Host "verify on Docker Hub, or pull one back with:"
Write-Host "  docker pull $ImagePrefix/registration-service`:$ImageTag"