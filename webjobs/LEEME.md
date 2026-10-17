# WebJobs de App Service (CU-05 y cierre de mes)

| Job | Horario (hora de Santiago) | Comando |
|---|---|---|
| `alertar-stock-bajo` | todos los días 06:30 | `manage.py alertar_stock_bajo` |
| `avisar-cierre-mes` | todos los días 00:15 | `manage.py avisar_cierre_mes` |

El horario es NCRONTAB de seis campos (segundo, minuto, hora, día, mes, día de la
semana) en `settings.job`, en la zona de `WEBSITE_TIME_ZONE` (`America/Santiago`,
ver `infra/modulos/appservice.bicep`).

El aviso de cierre corre **todos los días** y no sólo el día 1: el comando es
idempotente (un aviso por mes) y así, si una ejecución se pierde, la del día
siguiente lo crea igual.

## Por qué no van en `App_Data/` dentro del paquete

La compilación de App Service (Oryx) comprime toda la aplicación en
`output.tar.zst` y la extrae en `/tmp/<id>/` al arrancar: en `wwwroot` no queda
`App_Data/jobs`, y Kudu no ve los jobs (comprobado en el primer despliegue,
2026-10-17). Por eso se publican aparte, después de cada despliegue del código:

```powershell
python scripts/publicar_webjobs.py app-tivoscanea-nppckr
```

Cada job se sube como un zip autocontenido (`run.sh`, `settings.job` y
`scripts/webjob.sh`). El lanzador busca la aplicación y su entorno `antenv` en
`/home/site/wwwroot` o en `/tmp/*/`. Para ejecutar uno a mano: portal → App
Service → WebJobs → Run, y revisar su log.
