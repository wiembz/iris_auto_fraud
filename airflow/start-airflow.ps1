$ErrorActionPreference = "Stop"

$docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$desktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"

if (-not (Test-Path -LiteralPath $docker)) {
    throw "Docker CLI introuvable. Installez Docker Desktop avant de continuer."
}

try {
    & $docker info *> $null
}
catch {
    if (-not (Test-Path -LiteralPath $desktop)) {
        throw "Docker Desktop est introuvable."
    }

    Start-Process -FilePath $desktop
    Write-Host "Démarrage de Docker Desktop..."

    $ready = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        Start-Sleep -Seconds 5
        & $docker info *> $null
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
    }

    if (-not $ready) {
        throw "Le moteur Docker n'est pas prêt après cinq minutes."
    }
}

Push-Location $PSScriptRoot
try {
    & $docker compose config
    if ($LASTEXITCODE -ne 0) {
        throw "La configuration Docker Compose est invalide."
    }

    & $docker compose build
    if ($LASTEXITCODE -ne 0) {
        throw "La construction de l'image Airflow a échoué."
    }

    & $docker compose up -d
    if ($LASTEXITCODE -ne 0) {
        throw "Le démarrage d'Airflow a échoué."
    }

    & $docker compose ps
    Write-Host ""
    Write-Host "Airflow démarre sur http://localhost:8080"
    Write-Host "Le DAG iris_full_pipeline reste en pause et n'est pas déclenché."
}
finally {
    Pop-Location
}
