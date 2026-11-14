# Respaldo para la presentación: levanta TivoScanea en este computador, sin Azure ni
# internet, con el almacén de DATOS FICTICIOS «Almacén Ficticio Los Aromos» (no son del
# almacén piloto). Ver docs/PLAN_PRESENTACION.md.
#
#   .\scripts\demo_local.ps1              # usa los datos que ya hay
#   .\scripts\demo_local.ps1 -Recargar    # borra y vuelve a crear los datos ficticios
#   .\scripts\demo_local.ps1 -SoloPreparar  # deja todo listo sin abrir el servidor
#
# Requiere .env con DJANGO_DEBUG=True (los datos ficticios sólo se cargan en DEBUG).
param([switch]$Recargar, [switch]$SoloPreparar)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$servicio = Get-Service postgresql-x64-16 -ErrorAction SilentlyContinue
if (-not $servicio) {
    throw "No está instalado PostgreSQL 16 (servicio postgresql-x64-16)."
}
if ($servicio.Status -ne "Running") {
    Write-Host "PostgreSQL está detenido. Inícialo como administrador: Start-Service postgresql-x64-16"
    exit 1
}

$python = ".\.venv\Scripts\python.exe"
& $python manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw "Fallaron las migraciones." }
if ($Recargar) {
    & $python manage.py cargar_datos_ficticios --limpiar
    if ($LASTEXITCODE -ne 0) { throw "No se pudieron cargar los datos ficticios." }
}
& $python manage.py check
if ($LASTEXITCODE -ne 0) { throw "La verificación de Django falló." }

Write-Host ""
Write-Host "Listo. Abre http://127.0.0.1:8000 e ingresa con:"
Write-Host "  administradora: admin@demo.ficticio.test"
Write-Host "  vendedora:      vendedora@demo.ficticio.test"
Write-Host "  (la clave de demostración está en CLAUDE.md, «cargar_datos_ficticios»)"
if ($SoloPreparar) { exit 0 }
& $python manage.py runserver 127.0.0.1:8000
