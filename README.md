# TivoScanea

Plataforma web para almacenes de barrio chilenos: registro de productos por
escaneo de código de barras, ventas con descuento automático de stock, y
reportería mensual. Prototipo de Proyecto de Título (INACAP, TIHI84).

Ver [`CLAUDE.md`](./CLAUDE.md) para contexto de dominio, convenciones y
estado del proyecto.

## Requisitos

- Python 3.12
- PostgreSQL 16
- Windows + PowerShell (los comandos de abajo asumen esto; adaptar en otro SO)

## 1. Clonar y crear el entorno virtual

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Levantar PostgreSQL 16 local

Si no tenés PostgreSQL instalado, la forma más simple en Windows es con
winget:

```powershell
winget install --id PostgreSQL.PostgreSQL.16 --silent --accept-package-agreements --accept-source-agreements
```

Esto instala PostgreSQL como servicio de Windows (`postgresql-x64-16`,
puerto 5432) con un usuario `postgres` cuya contraseña por defecto en la
instalación silenciosa es `postgres`. **Cambiala si esta máquina no es
exclusivamente para desarrollo local.**

Verificar que el servicio esté corriendo:

```powershell
Get-Service postgresql-x64-16
```

Crear el rol y la base de datos de la app (ajustar la contraseña si la
cambiaste, y que coincida con tu `.env`):

```powershell
$env:PGPASSWORD = "postgres"
$psql = "C:\Program Files\PostgreSQL\16\bin\psql.exe"
& $psql -U postgres -h localhost -c "CREATE ROLE tivoscanea_user WITH LOGIN PASSWORD 'tivoscanea_dev_pw';"
& $psql -U postgres -h localhost -c "CREATE DATABASE tivoscanea_db OWNER tivoscanea_user;"
```

Para poder correr los tests (pytest-django crea una base de datos de test),
el rol necesita permiso `CREATEDB`:

```powershell
& $psql -U postgres -h localhost -c "ALTER ROLE tivoscanea_user CREATEDB;"
```

## 3. Variables de entorno

```powershell
cp .env.example .env
```

Editar `.env` con tus valores (o dejar los de ejemplo si coinciden con el
rol/base creados arriba). **`.env` nunca se sube al repositorio.**

## 4. Migraciones y superusuario

```powershell
python manage.py migrate
python manage.py createsuperuser   # pide email, nombre y password
```

> Si `migrate`/`makemigrations` se cuelgan sin mostrar error, es casi
> siempre porque PostgreSQL no está corriendo — revisá el paso 2.

## 5. Correr el servidor

```powershell
python manage.py runserver
```

Abrir `http://127.0.0.1:8000/` (redirige a login) o
`http://127.0.0.1:8000/admin/` para el panel de administración de Django.

## Tests y calidad de código

```powershell
python -m pytest
python -m pytest --cov=apps.inventario --cov=apps.usuarios --cov-report=term-missing
black apps tivoscanea manage.py
flake8 apps tivoscanea manage.py
```

## Estado actual

- Módulo **Usuarios** (auth por email + roles admin/vendedor): completo.
- Módulo **Productos e Inventario** (alta por escaneo/manual, edición, baja,
  búsqueda, categorías, alerta de stock bajo, bitácora de movimientos):
  completo, con tests.
- Módulo **Ventas**: solo modelos de datos (`Venta`, `DetalleVenta`), sin
  lógica ni vistas — próxima sesión.
- Módulo **Reportería**: no iniciado — sesión posterior a Ventas.
- Despliegue a Azure: no iniciado (documentado como pendiente en `CLAUDE.md`).
