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
| Interfaz | Plantillas Django + HTML/CSS/JS vanilla + **Bootstrap 5** (ver §2.4) |
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

### 2.4 Bootstrap 5 — resuelto (2026-10-14)

Se usa Bootstrap 5, como selecciona el Informe 2 (4,80/5 frente a React 2,95 y
Vue 3,70). La regla «sin Bootstrap» del CLAUDE.md anterior no venía del
docente ni de la asignatura: fue una propuesta del asistente y queda
descartada. Sigue prohibido cualquier framework SPA (React, Vue).

---

## 3. Modelo físico de datos

PostgreSQL 16. Toda columna `NOT NULL` salvo las marcadas `NULL`. Es la
Figura 7 del Informe 2 más las correcciones acordadas (marcadas con ★).
**Congelado desde el paquete 1.3.2**: si un servicio necesita algo que el
modelo no cubre, parar y preguntar. Cambios aprobados después: 1.4.3 (autor del
producto y del movimiento, motivo del ajuste; aprobado el 2026-10-14) y 1.4.4
(tabla `alerta` para CU-05 y el cierre de mes; aprobado el 2026-10-16).

Semántica de `movimiento_stock`: `salida` + `id_venta` = venta; `entrada` +
`id_venta` = restitución por anulación; `ajuste` = diferencia con signo y motivo.
El formulario de ajuste manual ofrece sólo los cuatro motivos manuales
(`MOTIVOS_AJUSTE_MANUAL`); los dos de la caja no se eligen a mano.

```sql
almacen
  PK  id_almacen      BIGSERIAL
      razon_social    VARCHAR(120)
      rut             VARCHAR(12)
      direccion       VARCHAR(200) NULL
      plan            VARCHAR(20)
      fecha_alta      TIMESTAMPTZ   DEFAULT now()
      activo          BOOLEAN       DEFAULT true
★     hora_limite_anulacion TIME    DEFAULT '23:59'  -- plazo de anulación, no horario de cierre
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
★ FK  id_usuario_creacion BIGINT NULL -> usuario   -- autor del alta (1.4.3); NULL si
                                                 -- se creó desde el admin de Django
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
★ FK  id_usuario_anulacion BIGINT NULL -> usuario
★     motivo_anulacion     VARCHAR(200) NULL
★     fecha_anulacion      TIMESTAMPTZ  NULL
  CK  estado IN ('vigente','anulada')
★ CK  ck_venta_anulacion_coherente: anulada <=> los tres campos llenos
      (motivo con length(trim) >= 5); no anulada <=> los tres NULL
★ CK  ck_venta_anulacion_posterior: fecha_anulacion >= fecha_hora
  IX  ix_venta_fecha (id_almacen, fecha_hora)
★ IX  ix_venta_anuladas (id_almacen, fecha_anulacion) WHERE estado = 'anulada'

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
★ FK  id_usuario      BIGINT -> usuario   -- NOT NULL: quién hizo el movimiento (1.4.3)
      tipo            VARCHAR(10)
      cantidad        INTEGER             -- entrada/salida > 0; sólo el ajuste lleva signo
★     motivo          VARCHAR(40)  NULL   -- sólo en ajustes
      fecha_hora      TIMESTAMPTZ   DEFAULT now()
  CK  tipo IN ('entrada','salida','ajuste')
★ CK  ck_movimiento_stock_cantidad (en los dos sentidos):
        (tipo IN ('entrada','salida') AND cantidad > 0 AND motivo IS NULL)
     OR (tipo = 'ajuste' AND cantidad <> 0 AND motivo IS NOT NULL)
★ CK  ck_movimiento_stock_motivo: motivo IS NULL OR motivo IN
        ('Diferencia de inventario','Producto dañado','Producto vencido',
         'Corrección administrativa',            -- los cuatro manuales
         'Venta sin stock registrado','Alta rápida en caja')  -- los genera la caja
  IX  ix_mov_prod_fecha (id_producto, fecha_hora)
★ IX  ix_mov_almacen_fecha (id_almacen, fecha_hora)  -- ajuste de rendimiento

★ acceso_reporte
  PK  id_acceso       BIGSERIAL
  FK  id_almacen      BIGINT -> almacen
  FK  id_usuario      BIGINT -> usuario
      mes_consultado  DATE          -- primer día del mes consultado
      fecha_hora      TIMESTAMPTZ   DEFAULT now()
  IX  ix_acceso_almacen_fecha (id_almacen, fecha_hora)

★ franja_horaria
  PK  id_franja       BIGSERIAL
  FK  id_almacen      BIGINT -> almacen
      nombre          VARCHAR(20)
      orden           SMALLINT
      hora_inicio     TIME
      hora_fin        TIME          -- EXCLUSIVA: la franja es [inicio, fin)
  UQ  uq_franja_almacen_nombre (id_almacen, nombre)
  UQ  uq_franja_almacen_orden  (id_almacen, orden)
  IX  ix_franja_almacen        (id_almacen, orden)

★ alerta                                  -- 1.4.4: avisos del panel del administrador
  PK  id_alerta        BIGSERIAL
  FK  id_almacen       BIGINT -> almacen
      tipo             VARCHAR(20)
      fecha_referencia DATE          -- día revisado (stock_bajo) o 1.er día del mes (cierre_mes)
      mensaje          VARCHAR(200)
      fecha_hora       TIMESTAMPTZ   DEFAULT now()
      fecha_vista      TIMESTAMPTZ   NULL
  FK  id_usuario_vista BIGINT NULL -> usuario
  CK  ck_alerta_tipo: tipo IN ('stock_bajo','cierre_mes')
  CK  ck_alerta_vista_coherente: fecha_vista e id_usuario_vista ambos NULL o ambos llenos
  UQ  uq_alerta (id_almacen, tipo, fecha_referencia)   -- comandos idempotentes
  IX  ix_alerta_pendientes (id_almacen, fecha_hora) WHERE fecha_vista IS NULL
```

Nombres de restricciones sin nombre en la Figura 7: `ck_usuario_rol`,
`ck_producto_stock_actual`, `ck_venta_estado`, `ck_detalle_venta_cantidad`,
`ck_movimiento_stock_tipo`. `apps/almacenes/test_esquema.py` verifica contra
PostgreSQL tipos, nulabilidad, restricciones e índices.

**Hora local:** toda comparación de reloj de pared (plazo de anulación,
franjas) usa `(fecha_hora AT TIME ZONE 'America/Santiago')`, nunca UTC
(`ZONA_HORARIA_ALMACEN` en `apps/almacenes/models.py`; `TruncTime(...,
tzinfo=...)` en el ORM). Una franja con `hora_inicio > hora_fin` cruza la
medianoche: usar `condicion_franja()`, nunca `BETWEEN`.


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

- `apps/almacenes/aislamiento.py`: las diez tablas heredan de
  `ModeloAislado`/`ModeloDeAlmacen`. **Toda consulta de la aplicación es
  `Modelo.objects.del_almacen(almacen)...`**; sin eso, `objects` lanza
  `ConsultaSinAlmacenError` (también `filter(id_almacen=...)` a mano).
  `create()` sobre una consulta fijada asigna el almacén.
- `Modelo.sin_aislamiento` es el default manager de Django (admin, login,
  validación de unicidad, relaciones inversas como `venta.detalles`). En
  código propio sólo para consultas intencionalmente transversales.
  Limitación: un `Subquery` construido sin `del_almacen` no se detecta.
- Pruebas con dos almacenes en `apps/almacenes/test_aislamiento.py`
  (fixtures `datos_a`/`datos_b` en `conftest.py`). Son parte de la
  definición de terminado.

---

## 4. Casos de uso (en este orden, cada uno con pruebas en verde)

**CU-01 · Registrar producto (Administrador).** Escanear → buscar → formulario
con el código precargado → nombre, categoría, precio, stock inicial → guardar
con movimiento `entrada`. 2a: el código ya existe → ofrecer sumar stock.
1a: código ilegible → digitar a mano.

**CU-02 · Registrar venta (Vendedor) — caso crítico.** Escanear cada producto
→ detalle → total → medio de pago → confirmar → descontar stock, movimientos
de salida y comprobante, **todo en una sola transacción**.
- 2a: producto no registrado → **alta rápida desde la caja**, también por el
  vendedor (decidido 2026-10-14): sólo código, nombre y precio; categoría NULL
  y el administrador la completa después. Se graba el autor
  (`producto.id_usuario_creacion`). El producto se crea **fuera** de la
  transacción de la venta: si la venta se abandona, el producto queda con
  stock 0 y sin movimientos (comportamiento esperado). La venta usa el mismo
  servicio que 6a con motivo «Alta rápida en caja» y sin mostrar el aviso. No
  hay pantalla de «productos por revisar»: se consulta por el motivo.
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

**CU-03 · Anular venta (Administrador y Vendedor — decidido 2026-10-14; corrige
la ficha CU-03 del informe).** El control no es el permiso sino el registro de
quién, cuándo y por qué. Venta vigente dentro del plazo →
confirmar → `anulada` + movimientos `entrada` que restituyen stock.
- **Plazo: hasta las 23:59 del día de la venta, parametrizable por almacén.**
  Motivo: cerrado el día, el reporte ya se consultó y la reposición ya se
  decidió; anular después cambia el pasado.
- Registrar siempre **quién anuló y por qué** (motivo obligatorio).
  Implementado: `limite_anulacion()` / `anulacion_en_plazo()` en
  `apps/ventas/servicios.py` (incluye el minuto 23:59 completo).
- Limitación declarada: un almacén que cierra después de medianoche no queda
  bien modelado (la venta de la 01:30 es del día calendario en que ocurrió).
  Un almacén de Magallanes (sin horario de invierno) queda desfasado 1 h.
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

Infraestructura (paquete 1.6), **perfil sin gateway (decidido 2026-10-17)**: el
Application Gateway con WAF del diseño original (~USD 320/mes) no es costeable
con el crédito de Azure for Students; **no reintroducirlo** sin que se pida. App
Service Linux B1 como entrada pública (HTTPS obligatorio, TLS 1.2, identidad
administrada, integración de red de salida); PostgreSQL Flexible B1ms en subred
delegada sin IP pública, NSG sólo 5432 desde la subred de aplicación; Key Vault
para secretos, abierto sólo a esa subred (nunca en `settings.py`, `.env`
versionado ni como valor en variables del App Service: sólo referencias);
despliegue con OIDC federado desde GitHub Actions. Presupuesto objetivo ~USD
13–15/mes; ver `infra/README.md`. En local: PostgreSQL con
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
| Exactitud de inventario | Movimientos tipo `ajuste` **excluyendo motivo «Alta rápida en caja»** (un producto que nace en el mesón no es una diferencia de inventario) |
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

## Estado actual del código

- **1.4.1 (hecho):** Django 5.2 LTS, CI (`verificaciones`: black, flake8,
  migraciones al día, pytest sobre PostgreSQL 16) y check de despliegue
  `tivoscanea.E001` que rechaza la SECRET_KEY del CI (`tivoscanea/checks.py`;
  el pipeline de 1.6 debe correr `check --deploy --fail-level ERROR`).
- **1.3.2 (hecho):** las nueve tablas, migraciones desde cero, mixin de
  aislamiento, `crear_almacen()` con las cinco franjas, `anotar_franja()` en
  `apps/reporteria/servicios.py`.
- **1.4.2 (hecho):** CU-01 y CU-06.
  - Servicios: `apps/inventario/servicios.py` (registrar producto, sumar
    stock, editar sin tocar stock, categorías; `registrar_movimiento` impone
    el almacén del producto) y `apps/usuarios/servicios.py` (crear vendedor).
    Los errores para el usuario son `ReglaDeNegocioError`
    (`apps/almacenes/errores.py`).
  - `request.almacen` lo pone `AlmacenActualMiddleware`.
  - API DRF bajo `/api/` (namespace `api`): `producto_por_codigo` (ambos
    roles, la usará la caja) y `entrada_stock` (sólo admin, permiso
    `EsAdministrador`). Sesión + CSRF.
  - Pantallas Bootstrap 5 (copiado en `static/vendor/bootstrap-5.3.8/`, sin
    CDN): inicio, inventario (vendedor sólo consulta), escanear
    (`static/js/escanear.js`, foco en el campo de escaneo), alta, edición,
    categorías y vendedores. Formularios con `FormularioBootstrap`.
- **1.4.3 (hecho, integrado en main):** CU-02, CU-03 y ajuste de inventario.
  - `apps/ventas/servicios.py`: `registrar_venta` (una transacción; precio del
    servidor; 6a lanza `StockInsuficienteError` sin escribir nada salvo con
    `confirmar_diferencias`; alta rápida verificada en el servidor: el producto
    no tiene movimientos) y `anular_venta` (ambos roles, motivo ≥ 5, plazo).
  - Un solo camino de ajuste: `aplicar_ajuste` en `apps/inventario/servicios.py`
    (6a, alta rápida y ajuste por conteo del administrador).
  - API: `POST /api/ventas/` (201 / 409 con diferencias / 400) y
    `POST /api/productos/alta-rapida/` (201 / 409 con el existente / 400).
  - Pantallas: caja (`static/js/caja.js`), ventas del día, comprobante
    imprimible (`@media print` en `tivoscanea.css`) y ajuste de inventario.
  - Indicador de exactitud: `ajustes_de_exactitud()` en
    `apps/reporteria/servicios.py` (excluye la alta rápida).
- **1.4.4 (hecho, en rama `1.4.4-reporteria`):** CU-04 y CU-05.
  - `apps/reporteria/servicios.py`: `reporte_mensual` (sólo ventas vigentes; mes en
    hora local; `RANK()` con empates para los más vendidos, top 10;
    `SUM(...) OVER ()` para participaciones; `LAG()` para la variación mensual) y
    `consultar_reporte_mensual` (registra `acceso_reporte` y da por visto el aviso
    de cierre de ese mes). Consultas constantes, no crecen con las ventas.
  - Día de la semana: promedio por ocurrencias del día en el período (un mes trae 4
    o 5 de cada uno). Franjas: todas, con su horario.
  - Comparación (3a): sólo entre meses consecutivos y **completos**. No se compara
    un mes en curso, un mes sin mes anterior con ventas, ni uno que empezó antes de
    `inicio_de_registros()` (alta del almacén o primera venta, lo anterior); el
    motivo se muestra en pantalla.
  - Umbral de stock bajo: `stock_actual <= stock_minimo`
    (`productos_con_stock_bajo()` en `apps/inventario/servicios.py`, fuente única).
  - Comandos `alertar_stock_bajo` y `avisar_cierre_mes` (`--fecha AAAA-MM-DD`),
    idempotentes, recorren almacenes activos. El panel muestra la revisión de stock
    más reciente sin ver y los cierres sin ver; «Entendido» las marca vistas.
  - Pantalla `/reportes/mensual/?mes=AAAA-MM` y `GET /api/reportes/mensual/` (sólo
    admin). Filtro `porcentaje` en `formato`.
- **1.4.4 y 1.4.5 integrados en main** (`291afd1`).
- **1.4.5:**
  - `apps/almacenes/test_sistema.py`: los seis CU de punta a punta con login real y
    CSRF activo (jornada completa CU-06 → 01 → 02 con 2a y 6a → 03 → 05 → 04), los
    alternativos y seguridad entre almacenes.
  - `manage.py cargar_datos_ficticios [--dias N] [--semilla S] [--limpiar]`: almacén
    de demostración «Almacén Ficticio Los Aromos» (`admin@demo.ficticio.test` /
    `vendedora@demo.ficticio.test`, clave `clave-ficticia-123`). Sólo con DEBUG;
    todo por servicios y luego fechado hacia atrás. Patrones inventados, no medición.
  - `pruebas_carga/locustfile.py` (Locust en `pruebas_carga/requirements.txt`): escaneo y
    venta; sale con código 1 si el p95 de caja supera 2 s. Pendiente: correrla
    contra el App Service (1.6).
- **1.6 (en curso, rama `1.6-despliegue`; sin suscripción de Azure aún):**
  - `infra/` en Bicep (ver `infra/README.md`: decisiones, costos, pasos). Compila
    y pasa el lint; nunca se ha aplicado. Fase 2 opcional para dominio propio
    con certificado administrado. Workflow `.github/workflows/despliegue.yml`.
  - Producción con `DJANGO_PRODUCCION=True`: WhiteNoise con manifiesto, cookies
    seguras, HSTS, proxy TLS, `CSRF_TRUSTED_ORIGINS`, `sslmode=require`, log a
    stdout. App Service corre al arrancar `check --deploy`, `migrate`,
    `collectstatic` y `gunicorn`. Probado en `tivoscanea/test_produccion.py`.
  - Dependencias: `requirements.txt` sólo servidor (agrega gunicorn y whitenoise);
    `requirements-dev.txt` pruebas y calidad (lo instala el CI).
  - Corregido: `DEBUG` se leía como texto («False» era verdadero) desde 1.4.1.
  - Bootstrap sin las líneas `sourceMappingURL` (ver su `LEEME.txt`).
  - Scheduler: WebJobs del App Service (decidido 2026-10-17) en
    `webjobs/` → `scripts/publicar_webjobs.py` (API de Kudu, tras cada despliegue;
    Oryx comprime la app y `App_Data/` no llega) → `scripts/webjob.sh` → `manage.py`. Stock bajo a
    las 06:30 y aviso de cierre a las 00:15, ambos diarios (idempotentes), en hora
    de Santiago. Ver `webjobs/LEEME.md`.
  - Pendiente: monitoreo, HSTS según dominio, verificar los WebJobs en Azure.
- **Operador de la plataforma (2026-10-17, no estaba en el brief):** alta de
  almacenes en `/plataforma/almacenes/`, sólo para `is_superuser`
  (`operador_requerido`). `alta_almacen()` crea almacén, franjas y primer
  administrador todo o nada; `normalizar_rut()` valida el DV y guarda
  «12345678-9». El operador vive en un almacén de plan `operacion` (el modelo exige
  `id_almacen`), excluido de la lista; lo crea `manage.py crear_operador`, que pide
  la contraseña. No hay registro autoservicio.
- **`docs/GUIA_TIVOSCANEA.md`**: guía de la aplicación para Claude Desktop (sin
  acceso al código). **Al cambiar un comportamiento visible, actualizarla.**
- Prueba de carga en Azure: `manage.py preparar_almacen_carga` (sólo almacenes de plan
  `carga`, nunca el piloto) + `pruebas_carga/locustfile.py` con `CARGA_EMAIL/CLAVE`.
- Montos en pantalla con el filtro `pesos` (`{% load formato %}`).
- Textos en español de Chile con tuteo («Ingresa», «Escribe»), sin voseo.
- Regla que se mantiene: **toda variación de `stock_actual` pasa por la capa
  de servicios y genera un `movimiento_stock`**.

## Comandos

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py runserver
python -m pytest
black apps tivoscanea manage.py conftest.py pruebas_carga scripts
flake8 apps tivoscanea manage.py conftest.py pruebas_carga scripts
python manage.py cargar_datos_ficticios --limpiar   # datos de demostración
python manage.py alertar_stock_bajo; python manage.py avisar_cierre_mes
python manage.py makemigrations && python manage.py migrate
```

Si `makemigrations`/`migrate` se cuelgan sin error, casi siempre es que
PostgreSQL no está corriendo en `localhost:5432`: `Get-Service postgresql-x64-16`.
