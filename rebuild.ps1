# Check if Docker is running
if (-not (Get-Process -Name "com.docker.backend" -ErrorAction SilentlyContinue)) {
    Write-Host "Docker is not running. Please start Docker Desktop and try again."
    exit 1
}


# Shut down current Docker Compose setup (including orphans)
Write-Host "`n🧹 Stopping and removing existing containers..."
docker compose down --remove-orphans

# Build images
Write-Host "`n🔨 Building images..."
docker compose build

# Bring everything up
Write-Host "`n🚀 Starting containers..."
docker compose up -d

Write-Host "`n✅ Rebuild complete."
