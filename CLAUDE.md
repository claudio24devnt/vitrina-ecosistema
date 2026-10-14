# TivoScanea — Brief de construcción

Fuente de verdad: el brief del proyecto con las correcciones acordadas el
2026-10-14 (respuestas a las siete decisiones). Sale de los Informes 1 y 2 ya
evaluados: **si el código contradice esto, el código está mal**. Si algo de
aquí parece equivocado, dilo antes de programarlo.

---

## 1. Qué es y para quién

Plataforma web que reemplaza el cuaderno de ventas de un almacén de barrio
chileno. Tres capacidades, en orden de importancia:

1. **Registrar productos escaneando el código de barras**, sin digitar.
2. **Registrar ventas descontando el stock en la misma transacción.**
3. **Reporte mensual**: productos más vendidos, días y horarios de mayor
   demanda, comparación con meses anteriores. Es el diferenciador comercial
   (Loyverse gratis limita la analítica a 31 días; Bsale cuesta ~$47.000/mes).

Usuario real: 47 años en promedio, atiende solo o con un ayudante, hoy anota
en papel. **Si una pantalla necesita explicación, está mal diseñada.**

Proyecto de título de Claudio Escobar (TIHI84, INACAP). Se evalúa, se defiende
ante un docente y se pilotea en un almacén real.

---

## 2. Reglas que no se negocian

### 2.1 Stack

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.12 |
| Framework | **Django 5.2 LTS** (soporte extendido hasta abril 2028) + Django REST Framework |
| Base de datos | PostgreSQL 16 |
| Interfaz | Plantillas Django + HTML/CSS/JS — **Bootstrap: PENDIENTE, ver §2.4** |
| Nube | Azure: App Service (Linux) + Database for PostgreSQL Flexible Server |
| Pruebas | pytest + pytest-django |
| Calidad | flake8 + black (line-length 95, ver `pyproject.toml` / `setup.cfg`) |
| CI/CD | GitHub Actions (`.github/workflows/ci.yml`) |
| Secretos | Azure Key Vault + identidad administrada |

**No introduzcas** React, Vue, Celery, Redis, Docker Compose multi-servicio,
GraphQL ni otro ORM. Si crees que hace falta, dilo y espera respuesta.

### 2.2 Metodología: Modelo en V

Ningún módulo está terminado sin su nivel de prueba escrito y pasando:
modelo ↔ unitarias de modelos/restricciones; servicios ↔ unitarias de
servicios; API/vistas ↔ integración; módulo ↔ sistema; producto ↔ aceptación
con el almacén piloto. No avances de fase con la anterior en rojo.

### 2.3 Honestidad de los datos

Las líneas base de los indicadores **no están medidas** (levantamiento con el
almacén piloto en la semana 5).

- No inventes datos que simulen mediciones reales. Seeds y fixtures con
  marcas y personas **inventadas**, y un comentario arriba del archivo
  diciendo que son ficticios y no provienen del almacén piloto.
- Reporte sin datos suficientes → **dilo en la interfaz**, no tablas vacías
  ni gráficos en cero.
- Mes sin mes anterior comparable → omitir la comparación e indicar el motivo.

### 2.4 Bootstrap — decisión pendiente

El Informe 2 selecciona «HTML, CSS y JavaScript con Bootstrap» (4,80/5 frente
a React 2,95 y Vue 3,70). El CLAUDE.md anterior decía «sin Bootstrap, es un
requisito del proyecto» y no se sabe de dónde salió esa regla. Claudio lo
resuelve. **Hasta entonces, no tocar la capa de presentación.**

---

## 3. Modelo físico de datos

PostgreSQL 16. Toda columna `NOT NULL` salvo las marcadas `NULL`. Es la
Figura 7 del Informe 2 más tres correcciones (marcadas con ★).

```sql
almacen
  PK  id_almacen      BIGSERIAL
      razon_social    VARCHAR(120)
      rut             VARCHAR(12)
      direccion       VARCHAR(200) NULL
      plan            VARCHAR(20)
      fecha_alta      TIMESTAMPTZ   DEFAULT now()
      activo          BOOLEAN       DEFAULT true
  UQ  uq_almacen_rut (rut)

usuario
  PK  id_usuario      BIGSERIAL
  FK  id_almacen      BIGINT -> almacen
      nombre          VARCHAR(120)
      email           VARCHAR(150)
      hash_password   VARCHAR(128)
      rol             VARCHAR(10)
      fecha_creacion  TIMESTAMPTZ   DEFAULT now()
  UQ  uq_usuario_email (email)
  CK  rol IN ('admin','vendedor')
  IX  ix_usuario_almacen (id_almacen)

categoria
  PK  id_categoria    BIGSERIAL
  FK  id_almacen      BIGINT -> almacen
      nombre          VARCHAR(80)
  UQ  uq_categoria (id_almacen, nombre)

producto
  PK  id_producto     BIGSERIAL
  FK  id_almacen      BIGINT -> almacen
  FK  id_categoria    BIGINT NULL -> categoria
      codigo_barras   VARCHAR(20)
      nombre          VARCHAR(150)
      precio          NUMERIC(10,0)
      stock_actual    INTEGER       DEFAULT 0
      stock_minimo    INTEGER       DEFAULT 0
      fecha_creacion  TIMESTAMPTZ   DEFAULT now()
  UQ  uq_producto (id_almacen, codigo_barras)
  CK  stock_actual >= 0
  IX  ix_producto_codigo (codigo_barras)

venta
  PK  id_venta        BIGSERIAL
  FK  id_almacen      BIGINT -> almacen
  FK  id_usuario      BIGINT -> usuario
      fecha_hora      TIMESTAMPTZ   DEFAULT now()   -- confirmación
★     hora_inicio     TIMESTAMPTZ   NULL            -- apertura de la venta (indicador)
      total           NUMERIC(12,0)
      medio_pago      VARCHAR(20)
      estado          VARCHAR(10)   DEFAULT 'vigente'
  CK  estado IN ('vigente','anulada')
  IX  ix_venta_fecha (id_almacen, fecha_hora)

detalle_venta
  PK  id_detalle      BIGSERIAL
★ FK  id_almacen      BIGINT -> almacen
  FK  id_venta        BIGINT -> venta
  FK  id_producto     BIGINT -> producto
      cantidad        INTEGER
      precio_unitario NUMERIC(10,0)
      subtotal        NUMERIC(12,0)
  CK  cantidad > 0
  IX  ix_detalle_venta (id_venta)

movimiento_stock
  PK  id_movimiento   BIGSERIAL
★ FK  id_almacen      BIGINT -> almacen
  FK  id_producto     BIGINT -> producto
  FK  id_venta        BIGINT NULL -> venta
      tipo            VARCHAR(10)
      cantidad        INTEGER
      fecha_hora      TIMESTAMPTZ   DEFAULT now()
  CK  tipo IN ('entrada','salida','ajuste')
  IX  ix_mov_prod_fecha (id_producto, fecha_hora)

★ acceso_reporte
  PK  id_acceso       BIGSERIAL
  FK  id_almacen      BIGINT -> almacen
  FK  id_usuario      BIGINT -> usuario
      mes_consultado  DATE          -- primer día del mes consultado
      fecha_hora      TIMESTAMPTZ   DEFAULT now()
  IX  ix_acceso_almacen_fecha (id_almacen, fecha_hora)
```

**Pendiente de modelar (definido en §4, sin columna en la Figura 7):** quién
anuló y motivo obligatorio (CU-03), plazo de anulación y franjas horarias
parametrizables por almacén (CU-03, CU-04). Proponer el esquema y confirmarlo
antes de crearlo.

### Decisiones que se respetan

1. **`id_almacen` en toda tabla del dominio**, incluidas `detalle_venta` y
   `movimiento_stock` (redundante a propósito: el filtro obligatorio funciona
   igual en todas). El servicio impide la incoherencia:
   `detalle_venta.id_almacen == venta.id_almacen` y
   `movimiento_stock.id_almacen == producto.id_almacen`, cubierto por pruebas.
2. **`NUMERIC(n,0)` para montos** (el peso no tiene subdivisión).
3. **`TIMESTAMPTZ`** en toda marca de tiempo.
4. **Código de barras único por almacén**, no global.
5. **La venta no se borra al anularse**: cambia de estado y genera
   movimientos compensatorios.

Las columnas usan `db_column` explícito para respetar los nombres literales
(Django agregaría `_id` a los FK). `Usuario` mantiene los atributos Python
`id`/`password` (los exige `AbstractBaseUser`) mapeados a `id_usuario` /
`hash_password`; se autentica por `email`.

### Aislamiento multi-tenant — requisito

- Un manager/mixin **obliga** a filtrar por `id_almacen`: una consulta sin ese
  filtro **falla** en desarrollo, no devuelve datos.
- Pruebas con dos almacenes que verifican que ninguno puede leer, modificar
  ni contar datos del otro. Son parte de la definición de terminado.

---

## 4. Casos de uso (en este orden, cada uno con pruebas en verde)

**CU-01 · Registrar producto (Administrador).** Escanear → buscar → formulario
con el código precargado → nombre, categoría, precio, stock inicial → guardar
con movimiento `entrada`. 2a: el código ya existe → ofrecer sumar stock.
1a: código ilegible → digitar a mano.

**CU-02 · Registrar venta (Vendedor) — caso crítico.** Escanear cada producto
→ detalle → total → medio de pago → confirmar → descontar stock, movimientos
de salida y comprobante, **todo en una sola transacción**.
- 2a: producto no registrado → darlo de alta **sin abandonar la venta**.
- 6a: stock insuficiente → advertir y exigir confirmación explícita (no un
  botón que se apriete sin leer). Mensaje: «El sistema tiene 3 unidades y
  estás vendiendo 5. Si continúas, se registra una diferencia de inventario de
  2 unidades.» Al confirmar, en la misma transacción: (1) diferencia =
  cantidad − stock_actual; (2) movimiento `ajuste` por la diferencia;
  (3) `salida` por la cantidad vendida; (4) confirmar la venta. Nunca stock
  negativo.
- Registrar `hora_inicio` (apertura) además de `fecha_hora` (confirmación).
- Lector en **modo HID**: texto tecleado + `Enter`. Sin driver, SDK ni WebUSB.
  El campo de escaneo mantiene el foco.
- **Comprobante:** pantalla HTML imprimible con hoja de estilo de impresión
  (no PDF). Debe decir en lugar visible **«Comprobante interno de venta — no
  es boleta electrónica»**.

**CU-03 · Anular venta (Administrador).** Venta vigente dentro del plazo →
confirmar → `anulada` + movimientos `entrada` que restituyen stock.
- **Plazo: hasta las 23:59 del día de la venta, parametrizable por almacén.**
  Motivo: cerrado el día, el reporte ya se consultó y la reposición ya se
  decidió; anular después cambia el pasado.
- Registrar siempre **quién anuló y por qué** (motivo obligatorio).
- 2a: fuera de plazo → rechazar e informar el motivo.

**CU-04 · Reporte mensual (Administrador).** Seleccionar mes → más vendidos,
ventas por día de la semana y por franja horaria, comparación con meses
anteriores. **Cálculo al vuelo con funciones de ventana de PostgreSQL**, sin
tablas precalculadas; nunca traer todas las filas a Python. Cada consulta
registra un `acceso_reporte`.
- 2a: mes sin ventas → informar ausencia de datos.
- 3a: sin mes base comparable → omitir la comparación e indicar el motivo.
- Franjas iniciales (supuesto, no medición; parametrizables por almacén):
  Mañana 07:00–10:59 · Mediodía 11:00–13:59 · Tarde 14:00–17:59 ·
  Noche 18:00–21:59 · Resto 22:00–06:59.

**CU-05 · Alerta de stock bajo (Administrador).** Comando de gestión
(`manage.py`) invocable por un scheduler, **sin Celery**: compara
`stock_actual` con `stock_minimo` y genera alerta en el panel. 3a: ninguno bajo
el mínimo → no genera alerta.

**Cierre de mes** (temporizador del BPMN del proceso 3): tarea programada que
**sólo avisa** que el reporte del mes está disponible. No precalcula nada.

**CU-06 · Gestionar vendedor (Administrador).** Crear usuario rol `vendedor`
(registra ventas y consulta stock), contraseña con hash. 2a: correo ya
registrado → rechazar e informar. El vendedor **no** ve reportes ni modifica
precios.

---

## 5. Arquitectura

Navegador (plantillas Django) → JSON/HTTPS → API REST (DRF: venta
transaccional, descuento de stock, agregación mensual) → PostgreSQL. Procesos
programados como comandos de Django (alerta diaria de stock, aviso de cierre
de mes). Toda integración externa pasa por la API REST. **SII (boleta) y
pasarela de pago quedan fuera de la v1**: documentar puntos de extensión, no
implementarlos.

Infraestructura (paquete 1.6): Application Gateway con WAF (OWASP) como único
componente con IP pública, TLS ahí, NSG sólo 443; App Service Linux en subred
privada con identidad administrada; PostgreSQL Flexible Server con Private
Endpoint, NSG sólo 5432 desde la subred de aplicación; Key Vault para secretos
(nunca en `settings.py`, `.env` versionado ni variables del App Service);
despliegue con OIDC federado desde GitHub Actions. En local: PostgreSQL con
datos ficticios; **ninguna prueba toca datos reales de un almacén**.

---

## 6. Pruebas

Casos CP-01 a CP-14 del informe. Mínimo:
- **Unitarias:** restricciones (`stock_actual >= 0`, `cantidad > 0`, enums de
  `rol`/`estado`/`tipo`), subtotal y total, transición de estado de la venta.
- **Integración:** venta completa en una transacción; si falla el descuento de
  stock, **nada** queda registrado (probarlo forzando el fallo).
- **Sistema:** los seis CU con sus alternativos; CU-02 2a explícitamente.
- **Aislamiento multi-tenant** (§3).
- **No funcionales:** p95 < 2 s en el punto de venta (Locust); vendedor nuevo
  completa una venta en < 3 intentos sin ayuda.
- **Cobertura:** 80 % en servicios y modelos (la interfaz no cuenta). Si
  llegar a 80 % exige pruebas de relleno, avisar: se baja a 70 %.

---

## 7. Indicadores

No se inventan ni se rellenan; el sistema debe **poder** medirlos. Sin línea
base se muestran como «Por medir en el levantamiento», nunca como cero.

| Indicador | Fuente |
|---|---|
| Tiempo de registro de venta | `venta.fecha_hora − venta.hora_inicio` |
| Quiebres de stock | Serie de `movimiento_stock` por producto (llegada a 0 y reposición) |
| Exactitud de inventario | Movimientos tipo `ajuste` |
| Uso de la reportería | Tabla `acceso_reporte` |

SLA: p95 < 2 s en el punto de venta; respaldo diario con retención de 7 días;
RPO 24 h, RTO 4 h.

---

## 8. Normas

ISO/IEC 25010; OWASP Top 10; Ley 19.628 (los datos de ventas son del almacén);
Ley 21.210 y Res. Ex. 74 y 108 de 2020: la v1 **no** emite documentos
tributarios — nunca afirmar en la interfaz que el comprobante es una boleta.

---

## 9. Orden de trabajo (EDT) — detenerse al final de cada bloque

1. **1.4.1 Entorno y repositorio** — Django, PostgreSQL local, flake8, black,
   pytest, CI con las verificaciones en verde.
2. **1.3.2 Modelo de datos** — tablas de §3 desde cero (migraciones
   regeneradas, base local recreada), mixin multi-tenant, pruebas de
   aislamiento.
3. **1.4.2 Productos e Inventario** — CU-01, CU-06, movimientos de stock.
4. **1.4.3 Ventas** — CU-02 y CU-03.
5. **1.4.4 Reportería** — CU-04 y CU-05.
6. **1.4.5 Integración** y pruebas de sistema.
7. **1.6 Despliegue.**

---

## 10. Convenciones

- Dominio en español, igual que el modelo; la infraestructura de Django
  mantiene sus nombres. Sin traducciones a medias.
- Interfaz, mensajes y comentarios en **español de Chile**. Errores para el
  almacenero («Ese código de barras ya está registrado en Bebidas»), no para
  el desarrollador.
- Lógica de negocio en **`servicios.py`** por app. Las vistas orquestan, los
  servicios deciden.
- Commits en español, imperativo, con el paquete EDT adelante:
  `1.4.3 Descontar stock dentro de la transacción de venta`.

## 11. Cómo trabajar

- Antes de cada bloque: tres líneas con qué se hará y qué archivos se tocan.
- Si algo del brief parece equivocado, decirlo. No inventar requisitos: si
  falta un dato, preguntar.
- Nada se marca terminado con pruebas en rojo, ni con pruebas ajustadas al
  código en vez de al revés.
- Al cerrar un bloque: qué quedó fuera y qué riesgo introduce.

## 12. Contexto

146.000 almacenes de barrio en Chile (Sercotec, 2024), 81 % con lápiz y
papel. Precio modelado $14.990/mes IVA incluido — **hipótesis, no
hardcodear**. Proyección: 1.655 almacenes al año 5 (por eso el multi-tenant no
es opcional). Equipo: una persona; cada dependencia se mantiene sola cinco
años.

---

## Estado actual del código (a migrar)

`main` tiene un prototipo previo al brief: apps `usuarios`, `inventario`,
`ventas` (caja, historial, anulación), `reporteria` (vacía) y el comando
`cargar_datos_prueba`. **No cumple el modelo de §3** (sin `almacen` ni
`id_almacen`, montos con 2 decimales, código de barras único global, plazo de
anulación de 30 min inventado, `services.py` en inglés, seed con marcas
reales). Se reescribe en los bloques 1.3.2 → 1.4.3. La regla vigente del
prototipo que se mantiene: **toda variación de `stock_actual` pasa por la
capa de servicios y genera un `movimiento_stock`**.

## Comandos

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py runserver
python -m pytest
black apps tivoscanea manage.py
flake8 apps tivoscanea manage.py
python manage.py makemigrations && python manage.py migrate
```

Si `makemigrations`/`migrate` se cuelgan sin error, casi siempre es que
PostgreSQL no está corriendo en `localhost:5432`: `Get-Service postgresql-x64-16`.
