# TivoScanea — Guía de la aplicación

> **Para Claude (Desktop u otro asistente):** este documento describe cómo funciona
> TivoScanea tal como está desplegada (actualizado al 2026-10-17). Úsalo para
> entender la aplicación, responder preguntas sobre ella y ayudar a su autor a
> detectar y describir correcciones. **No tienes acceso al código ni a la base de
> datos**: el código lo modifica Claude Code en el repositorio, siguiendo el brief del
> proyecto (`CLAUDE.md`). Tu trabajo es dejar cada corrección lista para pasársela
> (ver «Cómo reportar una corrección», al final).

---

## 1. Qué es y para quién

Plataforma web que reemplaza el **cuaderno de ventas de un almacén de barrio
chileno**. Proyecto de título de Claudio Escobar (TIHI84, INACAP): se evalúa, se
defiende ante un docente y se pilotea en un almacén real.

- **Usuario real:** almacenero de ~47 años, atiende solo o con un ayudante, hoy anota
  en papel. Regla de diseño: *si una pantalla necesita explicación, está mal diseñada*.
- **Tres capacidades, en orden de importancia:**
  1. Registrar productos **escaneando el código de barras**, sin digitar.
  2. Registrar ventas **descontando el stock en la misma transacción**.
  3. **Reporte mensual**: más vendidos, días y horarios de mayor demanda, comparación
     con meses anteriores (el diferenciador comercial frente a Loyverse o Bsale).
- **Idioma:** español de Chile, con tuteo («Ingresa», «Escribe»), sin voseo.
  Montos en pesos sin decimales (`$1.990`).

**Producción:** https://app-tivoscanea-nppckr.azurewebsites.net

---

## 2. Roles

| Rol | Quién es | Qué puede hacer |
|---|---|---|
| **Operador** | El autor del proyecto (dueño de la plataforma) | Dar de alta almacenes con su primer administrador (pantalla «Almacenes»). Además es administrador de su propio almacén «de operación». |
| **Administrador** | El dueño del almacén | Todo lo del almacén: productos, stock, categorías, vendedores, ajustes de inventario, reporte mensual, alertas. También vende. |
| **Vendedor** | Quien atiende la caja | Registrar y anular ventas, consultar el inventario. **No** ve reportes, **no** cambia precios ni stock a mano, **no** crea usuarios. |

Cada almacén ve **sólo sus propios datos** (multi-almacén aislado): un usuario nunca
puede ver ni tocar productos, ventas o usuarios de otro almacén.

---

## 3. Pantallas

Todas usan Bootstrap 5 y funcionan en computador y celular. Menú superior verde.

### Para todos (con sesión)

| Pantalla | Ruta | Qué hace |
|---|---|---|
| Ingresar | `/cuentas/login/` | Correo y contraseña. |
| Inicio | `/` | Botones grandes (Abrir caja, Escanear, Inventario, Reporte según el rol), cifras de productos y stock bajo; al administrador le muestra las **alertas** (stock bajo y «ya está disponible el reporte de…») con «Ver» y «Entendido». |
| **Caja** | `/ventas/caja/` | Punto de venta (ver §4.2). El campo de escaneo mantiene el foco: el lector de código de barras «escribe» el código y presiona Enter. |
| Ventas del día | `/ventas/` | Ventas de un día (hoy por omisión), total vendido, anuladas tachadas. |
| Comprobante | `/ventas/<n>/` | Comprobante imprimible de una venta; dice en lugar visible **«Comprobante interno de venta — no es boleta electrónica»**. Desde aquí se anula. |
| Inventario | `/productos/` | Lista con búsqueda y filtro «sólo stock bajo». El vendedor sólo consulta. |

### Sólo administrador

| Pantalla | Ruta | Qué hace |
|---|---|---|
| Escanear producto | `/productos/escanear/` | Escanear un código: si existe, muestra el producto y permite **sumar stock**; si no, lleva al alta con el código ya puesto. |
| Nuevo producto | `/productos/nuevo/` | Código, nombre, categoría, precio, stock mínimo, stock inicial. |
| Editar producto | `/productos/<id>/editar/` | Cambia datos y precio; **no** cambia el stock (eso va por entradas o ajustes). |
| Ajuste de inventario | `/productos/<id>/ajustar/` | Conteo físico → el sistema calcula la diferencia. Motivos: diferencia de inventario, producto dañado, producto vencido, corrección administrativa. |
| Categorías | `/productos/categorias/` | Crear categorías. |
| Vendedores | `/cuentas/vendedores/` | Crear vendedores (correo único en toda la plataforma). |
| Reporte | `/reportes/mensual/?mes=AAAA-MM` | Reporte mensual (ver §4.4). |

### Sólo operador

| Pantalla | Ruta | Qué hace |
|---|---|---|
| Almacenes | `/plataforma/almacenes/` | Lista de almacenes clientes y alta de uno nuevo: razón social, RUT (se valida el dígito verificador), dirección, plan, y nombre/correo/contraseña inicial del administrador. Crea todo o nada. |

---

## 4. Cómo funcionan los procesos

### 4.1 Registrar producto (CU-01)
Escanear → si el código **no existe**, formulario con el código precargado → guardar.
El stock inicial queda registrado como un movimiento de **entrada**.
- Código ilegible: se digita a mano en el mismo campo.
- Código **ya registrado**: no se duplica; avisa «Ese código de barras ya está
  registrado en *Categoría*» y ofrece **sumar stock**.
- El código de barras es único **por almacén** (dos almacenes pueden tener el mismo).

### 4.2 Registrar venta (CU-02) — el caso crítico
Escanear cada producto → se arma el detalle → total → medio de pago (efectivo,
débito, crédito, transferencia) → confirmar. Al confirmar, **en una sola transacción**:
se descuenta el stock, se registran los movimientos de salida y se emite el
comprobante. Si algo falla, **no queda nada** registrado.
- **Stock insuficiente (6a):** el sistema no deja seguir sin confirmación explícita:
  «El sistema tiene 3 unidades de «X» y estás vendiendo 5. Si continúas, se registra
  una diferencia de inventario de 2 unidades.» Si se confirma, registra un **ajuste**
  por la diferencia y luego la venta. **El stock nunca queda negativo.**
- **Producto no registrado (2a):** desde la caja, cualquier rol puede darlo de alta
  rápido (sólo código, nombre y precio; sin categoría). El administrador completa la
  categoría después. Si la venta se abandona, el producto queda creado con stock 0.
- El **precio lo pone el servidor**, no la pantalla (no se puede alterar desde el
  navegador).
- Se guarda la hora de **apertura** y de **confirmación** de cada venta (sirve para
  medir cuánto tarda una venta).

### 4.3 Anular venta (CU-03)
Desde el comprobante, **administrador o vendedor**. Exige **motivo** (mínimo 5
letras) y registra **quién y cuándo**. La venta no se borra: queda «anulada» y el
stock vuelve con movimientos de entrada.
- **Plazo:** hasta las **23:59 del día de la venta** (hora de Chile). Después se
  rechaza explicando el motivo: cerrado el día, el reporte y la reposición ya se
  decidieron.

### 4.4 Reporte mensual (CU-04)
Sólo administrador. Se elige el mes (por omisión, el último mes cerrado). Muestra:
- **Ventas y total vendido** del mes (sólo ventas vigentes; las anuladas no cuentan).
- **Productos más vendidos** (top 10 por unidades; los empates comparten lugar).
- **Por día de la semana**, con **promedio por día** (un mes trae 4 o 5 de cada día).
- **Por franja horaria:** Mañana 07:00–10:59 · Mediodía 11:00–13:59 · Tarde
  14:00–17:59 · Noche 18:00–21:59 · Resto 22:00–06:59 (supuestos iniciales, no
  medición).
- **Comparación con meses anteriores** (hasta 6 meses), con variación % sólo entre
  meses **completos y consecutivos**. Si no se puede comparar, lo dice y explica por
  qué: mes en curso, mes anterior sin ventas, o almacén que empezó a mitad de mes.
- Mes **sin ventas**: lo dice en vez de mostrar tablas vacías.
- Cada consulta queda registrada (indicador «uso de la reportería»).

### 4.5 Alertas (CU-05 y cierre de mes)
Tareas programadas en Azure (WebJobs), hora de Chile:
- **06:30 — stock bajo:** si hay productos con stock **igual o menor** al mínimo,
  deja la alerta «Hay N productos con stock bajo el mínimo» en el inicio del
  administrador. Si no hay ninguno, no genera alerta.
- **00:15 — cierre de mes:** avisa «Ya está disponible el reporte de *mes*» cuando el
  mes anterior tuvo ventas. Corre a diario pero avisa una sola vez por mes.

### 4.6 Gestionar vendedor (CU-06)
El administrador crea vendedores con nombre, correo y contraseña (con las reglas de
seguridad de Django). Si el correo ya existe en cualquier almacén, lo rechaza.

---

## 5. Reglas que no se cambian sin decidirlo con el autor

- **Toda variación de stock deja un movimiento** (entrada, salida o ajuste con
  motivo). No hay forma de cambiar el stock «a mano».
- **La venta es una sola transacción**: o queda todo, o nada.
- **El comprobante no es boleta** y la aplicación nunca debe decir que lo es (la v1
  no emite documentos tributarios: Ley 21.210, SII fuera de alcance).
- **Honestidad de los datos:** no se inventan cifras. Sin datos suficientes, la
  pantalla lo dice; los indicadores sin línea base se muestran «por medir».
- **Aislamiento entre almacenes** en toda consulta.
- **Stack fijo:** Python 3.12, Django 5.2, PostgreSQL 16, plantillas Django +
  Bootstrap 5 + JavaScript simple. **No** React, Vue, Celery, Redis ni otros
  frameworks: si una corrección parece requerirlos, hay que plantearlo como decisión.

---

## 6. Datos (resumen del modelo)

| Tabla | Guarda |
|---|---|
| `almacen` | Razón social, RUT, plan, dirección, plazo de anulación |
| `usuario` | Nombre, correo, rol (admin/vendedor), almacén |
| `categoria`, `producto` | Catálogo: código de barras, precio, stock actual y mínimo, autor del alta |
| `venta`, `detalle_venta` | Ventas con total, medio de pago, estado, datos de anulación |
| `movimiento_stock` | Bitácora de entradas, salidas y ajustes (con motivo) |
| `franja_horaria` | Franjas del reporte, por almacén |
| `acceso_reporte` | Cada consulta del reporte |
| `alerta` | Avisos del panel (stock bajo, cierre de mes) y quién los vio |

---

## 7. Dónde corre (infraestructura)

- **Azure, región Brasil Sur**, suscripción Azure for Students (crédito vence el
  30/12/2026).
- **App Service B1 Linux** (la aplicación, HTTPS obligatorio) + **PostgreSQL 16**
  sin acceso desde Internet + **Key Vault** para secretos. ~USD 13–15/mes.
- **Despliegue automático:** cada cambio que entra a la rama `main` en GitHub pasa
  pruebas (CI) y se publica solo en ~5 minutos.
- Decisión de costo: **no hay Application Gateway ni WAF** (costaban ~USD 320/mes).

---

## 8. Limitaciones conocidas (no son errores)

- No emite boleta electrónica ni cobra con pasarela de pago (fuera de la v1).
- No hay registro autoservicio de almacenes: los crea el operador.
- Un almacén que cierra después de medianoche queda mal modelado (la venta de la
  01:30 cuenta para el día calendario en que ocurrió).
- Magallanes (sin horario de invierno) queda desfasado una hora.
- Sin monitoreo automático: si la app falla de noche, nadie recibe un aviso.
- No hay pantalla para «productos por revisar» de la alta rápida (se identifican por
  el motivo del ajuste).

---

## 9. Cómo reportar una corrección

Ayuda al autor a dejar cada problema así, para pegárselo a Claude Code:

```markdown
### Corrección: <título corto>

- **Pantalla / ruta:** p. ej. Caja (`/ventas/caja/`)
- **Rol con el que se probó:** operador / administrador / vendedor
- **Pasos:** 1. … 2. … 3. …
- **Qué pasó:** (texto exacto del mensaje de error, si hubo)
- **Qué debería pasar:**
- **Tipo:** error · texto/lenguaje · usabilidad · regla de negocio · nueva función
- **¿Contradice alguna regla de la sección 5?** sí/no — cuál
- **Prioridad para el piloto:** bloqueante / importante / puede esperar
```

Recomendaciones para ti al ayudar:
- Distingue un **error** (la app no hace lo que esta guía dice) de un **cambio de
  requisito** (la guía dice otra cosa de lo que el almacenero necesita). Los cambios
  de requisito pueden tocar el informe del proyecto: márcalos así.
- Revisa los textos con el criterio del usuario real: lenguaje de almacén, no de
  programador; tuteo; sin tecnicismos.
- **Nunca** pidas ni anotes contraseñas, ni datos reales de clientes del almacén.
