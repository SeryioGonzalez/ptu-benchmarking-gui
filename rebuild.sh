#!/bin/bash

# Check if Docker daemon is running
if ! docker info > /dev/null 2>&1; then
  echo "❌ Docker is not running. Please start Docker and try again."
  exit 1
fi

echo "🧹 Stopping and removing existing containers..."
docker compose down --remove-orphans

echo "🔨 Building images..."
docker compose build

echo "🚀 Starting containers..."
docker compose up -d

echo "✅ Rebuild complete."
