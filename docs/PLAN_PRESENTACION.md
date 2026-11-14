# Plan de la presentación ante el comité — martes 15 de diciembre de 2026, 19:30

Objetivo: que la demostración funcione aunque falle Azure, internet o el computador.
Se escribió el 2026-11-14 con datos medidos ese día.

## 1. Riesgos y qué los cubre

| Riesgo | Probabilidad | Qué lo cubre |
|---|---|---|
| Se acaba el crédito de Azure for Students y la suscripción se deshabilita | Baja: se gastan ~USD 0,45/día (~14/mes); oct. USD 18,6, nov. al día 14 USD 6,7 | Presupuesto `presupuesto-tivoscanea` (USD 20/mes) avisa por correo al 80 % del gasto real y al 100 % del pronóstico. Revisar el saldo (§3) |
| El crédito vence (30/12/2026) | No afecta al 15/12 | Decidir antes del 30/12 si se renueva o se pasa a pago (§3) |
| Un despliegue reinicia la app durante la demo (5–11 s por login, medido el 14/11) | Media si se despliega ese día | **Congelamiento**: no desplegar desde el 13/12 (§2) |
| Azure (Brazil South) o el App Service caen | Baja | **Plan B**: la demo local (`scripts/demo_local.ps1`), sin internet |
| Falla el internet de la sala | Media | Plan B local, o compartir internet desde el celular |
| Falla el computador | Baja | **Plan C**: video grabado de los flujos (§2, 14/12) |
| Un correo de recuperación cae en spam o no llega | Media (dominio de prueba `azurecomm.net`) | Mostrar el flujo con el correo ya recibido; o mostrar «Cambiar contraseña» del administrador |

## 2. Calendario

| Cuándo | Qué | Quién |
|---|---|---|
| Ahora | Revisar el saldo del crédito (§3) y anotarlo aquí | Autor |
| 1 de diciembre | Revisar el saldo de nuevo. Si queda menos de USD 15, decidir el pago (§3) | Autor |
| Hasta el viernes 11/12 | Último despliegue con cambios. Correr la prueba de carga y `verificar_produccion.py` | Autor + asistente |
| Sábado 12/12 | Crear la etiqueta `presentacion-2026-12-15` sobre lo desplegado (`git tag`) | Asistente |
| **13/12 en adelante** | **Congelamiento: nada a `main`** (cada merge despliega y reinicia) | Todos |
| Lunes 14/12 | Ensayo completo en Azure y con `demo_local.ps1`. Grabar el video del plan C (caja, CRUD de vendedores, reporte, recuperación de contraseña) | Autor |
| 15/12, 18:30 | `python scripts/verificar_produccion.py`; ingresar una vez como administrador y como vendedor (calienta la app); dejar abierta la demo local en otra pestaña | Autor |
| 15/12, 19:30 | Presentar. Si Azure no responde en 10 s, pasar a la pestaña local sin explicar de más | Autor |

## 3. Dinero: qué conviene

- **Azure for Students no admite cargar saldo** (no se le pueden «poner USD 20»). El saldo
  se ve en https://www.microsoftazuresponsorships.com/Balance con la cuenta de INACAP.
- **Para el 15/12 no hace falta pagar** si el saldo alcanza: desde hoy hasta el 30/12
  son ~46 días × USD 0,45 ≈ **USD 21**. Si el saldo es mayor a USD 25, no hacer nada.
- **Si el saldo es menor**, o para seguir después del 30/12 (piloto), la opción es
  **pasar la suscripción a pago por uso** («Upgrade» en el portal; pide tarjeta, y lo
  hace el autor, no el asistente). Costo esperado: ~USD 14/mes con la infraestructura
  actual. Antes de hacerlo, leer en el portal qué pasa con el crédito restante al
  cambiar de oferta. Alternativa a revisar: renovar Azure for Students si sigues
  siendo alumno (Microsoft ofrece la renovación cerca del vencimiento).
- El presupuesto es sólo un aviso: no corta el servicio ni cobra.

## 4. Plan B: demo local

```powershell
.\scripts\demo_local.ps1 -Recargar   # el 14/12: datos ficticios frescos (90 días)
.\scripts\demo_local.ps1             # el 15/12: abre http://127.0.0.1:8000
```

Necesita PostgreSQL 16 corriendo (`Get-Service postgresql-x64-16`) y `.env` con
`DJANGO_DEBUG=True`. Los datos del almacén «Los Aromos» son **ficticios**; dilo si el
comité pregunta. La recuperación por correo en local imprime el correo en la consola
de `runserver` (no lo envía): sirve para mostrar el enlace.

Ventaja: tiene 90 días de ventas ficticias, así que el reporte mensual y los
indicadores se ven completos. En Azure, un almacén de demostración nuevo muestra
«sin datos suficientes» (es lo correcto, pero luce menos).

## 5. Qué mostrar (orden sugerido, ~10 min)

1. Caja: escanear, alta rápida (2a), stock insuficiente (6a), comprobante.
2. Anular la venta (CU-03) y ver el stock restituido.
3. CRUD de vendedores: crear, cambiar contraseña, desactivar/reactivar, eliminar uno
   sin ventas e intentar eliminar uno con ventas (regla de integridad).
4. Reporte mensual e indicadores.
5. Seguridad: «¿Olvidaste tu contraseña?», bloqueo tras 5 intentos fallidos,
   aislamiento entre almacenes.
6. Infraestructura: Azure, monitoreo, presupuesto, log de acceso con tiempos.
