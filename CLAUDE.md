# TivoScanea

Plataforma web para almacenes de barrio chilenos (minimarkets de 1 a 3
trabajadores). Reemplaza cuaderno y calculadora con: alta de productos por
escaneo, registro de ventas con descuento automático de stock, y reportería
mensual comprensible para un comerciante sin formación técnica.

Este es el prototipo del Proyecto de Título (INACAP, TIHI84). El Informe 1
(formulación) y el Informe 2 (diseño técnico: arquitectura, modelo de datos,
KPI/SLA, plan de pruebas) ya fueron entregados y evaluados. **El código debe
coincidir con lo que dicen esos informes** — no te desvíes del diseño ya
documentado sin que el usuario lo confirme explícitamente.

## Stack

- Python 3.12, Django 6.1, Django REST Framework (instalado, sin endpoints
  propios todavía — se agregan solo cuando se pidan explícitamente).
- PostgreSQL 16 local (Azure Database for PostgreSQL Flexible Server en
  producción, todavía no configurado).
- Frontend: templates de Django + CSS propio (`static/css/estilos.css`) + JS
  vanilla. **Sin frameworks SPA (React/Vue) ni librerías de CSS tipo
  Bootstrap** — es un requisito explícito del proyecto, no un descuido.
- Tests: pytest + pytest-django. Cobertura ≥70% en módulos críticos
  (inventario y ventas) — actualmente inventario/usuarios están en ~96%.
- Calidad: black (line-length 95, ver `pyproject.toml`) + flake8 (ver
  `setup.cfg`). Deben pasar limpios antes de cada commit.

## Estructura

```
tivoscanea/          # settings, urls, wsgi/asgi
apps/
  usuarios/           # Usuario custom (AbstractBaseUser+PermissionsMixin), auth, roles
  inventario/         # Categoria, Producto, MovimientoStock + vistas completas
  ventas/             # Venta, DetalleVenta + caja (punto de venta), historial, anulación
  reporteria/          # vacía todavía (fase 6)
templates/            # base.html (layout compartido)
static/               # css/estilos.css, js/escaneo.js, js/venta.js
```

## Modelo de datos — nombres literales del diccionario de datos

Los nombres de columnas están en español porque así están documentados en el
Informe 2. **No los traduzcas ni los "normalices"** si tocás estos modelos.

- `Usuario`: PK y campo de password usan `db_column` (`id_usuario`,
  `hash_password`) para respetar el diccionario de datos, aunque los
  atributos Python siguen llamándose `id` y `password` — son los nombres que
  espera la maquinaria de auth de Django (`AbstractBaseUser`,
  `PermissionsMixin`, `set_password`, `check_password`, etc.). Se autentica
  por `email` (`USERNAME_FIELD = "email"`), no hay campo `username`.
- `Categoria`, `Producto`, `MovimientoStock` viven en `apps/inventario`.
- `Venta`, `DetalleVenta` viven en `apps/ventas`.
- Todos los FK usan `db_column` explícito para que la columna real se llame
  igual que en el diccionario (ej. `id_categoria`, `id_producto`, `id_venta`),
  porque Django por defecto le agregaría un sufijo `_id` al nombre del campo.

## Reglas de negocio ya implementadas (inventario)

- **Toda variación de `Producto.stock_actual` genera un `MovimientoStock`**,
  sin excepciones. La única forma correcta de cambiar stock es a través de
  `apps/inventario/services.py` (`registrar_entrada_stock`,
  `crear_producto_con_stock_inicial`), nunca asignando `producto.stock_actual`
  directamente desde una vista o un formulario.
- Alta por escaneo: si el código de barras ya existe, el flujo ofrece sumar
  stock al producto existente en vez de crear un duplicado (ver
  `apps/inventario/views.py::buscar_por_codigo` +
  `static/js/escaneo.js`). El lector de código de barras es un dispositivo
  HID (keyboard wedge): un `<input>` con foco automático que escucha `Enter`,
  sin cámara ni SDK — ver `templates/inventario/escaneo.html`.
- El campo `stock_actual` nunca se edita directamente desde el formulario de
  edición de producto (`ProductoForm` no incluye ese campo a propósito).
- **Observación de diseño (no resuelta, avisar si el informe dice lo
  contrario):** el diccionario de datos de `Producto` no incluye un campo de
  baja lógica (`activo`, etc.), así que "baja de producto" es un `delete()`
  real. Para no perder historial, `MovimientoStock.id_producto` y
  `DetalleVenta.id_producto` usan `on_delete=PROTECT`: un producto con
  movimientos o ventas asociadas no se puede eliminar (la vista captura
  `ProtectedError` y sugiere poner el stock en 0). Mismo criterio para
  `Categoria` con productos asociados.
- El módulo Inventario no tiene restricción por rol (el Informe 2 sólo exige
  rol-restricción explícita para anular ventas, ver `rol_requerido` en
  `apps/usuarios/decorators.py`).

## Reglas de negocio ya implementadas (ventas)

- Toda la lógica vive en `apps/ventas/services.py` (`registrar_venta`,
  `anular_venta`); las vistas sólo traducen `VentaError` a mensajes.
- `registrar_venta`: transacción atómica con `select_for_update` ordenado por
  PK. Si falta stock de cualquier producto no se guarda nada. El precio
  unitario se toma de `Producto.precio` en el servidor (nunca del cliente).
  Cada línea genera un `MovimientoStock` tipo `salida` con `id_venta`.
- `anular_venta`: sólo rol admin, sólo estado `vigente`, sólo dentro de
  `settings.PLAZO_ANULACION_VENTA_MINUTOS` (default 30). Repone stock con
  `MovimientoStock` tipo `entrada` ligado a la venta anulada (decisión de
  implementación: confirmar contra el Informe 2 si especifica otro tipo).
  La vista `anular` usa además `rol_requerido(RolUsuario.ADMIN)` → 403.
- La caja (`templates ventas/punto_venta.html` + `static/js/venta.js`) arma el
  carrito en el navegador reutilizando `inventario:buscar_por_codigo` y envía
  un POST normal con listas paralelas `id_producto` / `cantidad`.

## Qué falta (no implementado todavía, a propósito)

- **Reportería** (fase 6): productos más vendidos, ventas por día/franja
  horaria, comparación mensual, alerta de caída de ventas
  (`settings.UMBRAL_CAIDA_VENTAS_PORCENTAJE`, default 20%). Usar
  `annotate`/`aggregate`, nunca traer todas las filas a Python.
- **Despliegue** (fase 7): Dockerfile/Azure App Service, CI/CD, Key Vault.
- Datos de prueba (seed de ~50 productos + ventas históricas) — todavía no se
  generó; útil antes de probar reportería.

## Comandos frecuentes

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py runserver
python -m pytest                              # tests
python -m pytest --cov=apps.inventario --cov=apps.usuarios --cov-report=term-missing
black apps tivoscanea manage.py
flake8 apps tivoscanea manage.py
python manage.py makemigrations && python manage.py migrate
```

Si `makemigrations`/`migrate` se cuelgan sin error: es casi siempre porque
PostgreSQL no está corriendo en `localhost:5432` (Django intenta conectarse
al abrir el loader de migraciones y el connect TCP tarda mucho en fallar en
Windows). Verificar con `Get-Service postgresql-x64-16`.
