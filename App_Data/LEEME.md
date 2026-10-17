# WebJobs de App Service (CU-05 y cierre de mes)

App Service ejecuta lo que esté en `App_Data/jobs/triggered/<nombre>/` según el
horario NCRONTAB de seis campos (segundo, minuto, hora, día, mes, día de la
semana) de su `settings.job`, en la zona de `WEBSITE_TIME_ZONE`
(`America/Santiago`, ver `infra/modulos/appservice.bicep`).

| Job | Horario | Comando |
|---|---|---|
| `alertar-stock-bajo` | todos los días 06:30 | `manage.py alertar_stock_bajo` |
| `avisar-cierre-mes` | todos los días 00:15 | `manage.py avisar_cierre_mes` |

El aviso de cierre corre **todos los días** y no sólo el día 1: el comando es
idempotente (un aviso por mes) y así, si una ejecución se pierde, la del día
siguiente lo crea igual.

Cada `run.sh` llama a `scripts/webjob.sh`, que busca la aplicación y su entorno
virtual. **Verificar en el primer despliegue** ejecutando un job a mano desde el
portal (WebJobs → Run) y revisando su log.
