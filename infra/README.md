# Infraestructura de TivoScanea en Azure (paquete 1.6)

Infraestructura como código (Bicep) del §5, **perfil sin Application Gateway**
(decidido el 2026-10-17: el gateway con WAF cuesta ~USD 320/mes y el proyecto
corre con el crédito de Azure for Students).

**Todavía no se ha desplegado.** Compila y pasa el lint con Bicep CLI 0.48.1,
lo que valida sintaxis y propiedades contra los esquemas de cada versión de API,
pero no cuotas, regiones permitidas, nombres ocupados ni permisos: antes del
primer despliegue hay que correr `what-if` (abajo).

## Qué se crea

```
Internet ──HTTPS──▶ App Service B1 Linux (Python 3.12, identidad administrada,
                    │                   WebJobs de alertas)
                    │ integración de red (route-all)
          ┌─────────┴──────────────┐
          ▼ 5432, subred delegada  ▼ 443, service endpoint
   PostgreSQL 16 Flexible       Key Vault (RBAC)
   sin IP pública, respaldo 7 d  db-password, django-secret-key
```

| Archivo | Contenido |
|---|---|
| `main.bicep` | Orquesta los módulos; nombres únicos por grupo de recursos |
| `main.bicepparam` | Parámetros, sin secretos (se leen de variables de entorno) |
| `modulos/red.bicep` | VNet, subredes de app y de PostgreSQL con NSG, DNS privado |
| `modulos/keyvault.bicep` | Key Vault abierto sólo a la subred de la app |
| `modulos/postgres.bicep` | PostgreSQL 16 Flexible con acceso privado |
| `modulos/appservice.bicep` | Plan B1 y App Service; dominio propio opcional |
| `modulos/enlace-tls.bicep` | Activa TLS en el dominio propio |
| `modulos/acceso-keyvault.bicep` | Rol de lectura de secretos |
| `modulos/oidc.bicep` | Identidad federada de GitHub Actions |
| `../.github/workflows/despliegue.yml` | Despliegue tras el CI en verde sobre `main` |

## Costo esperado

| Recurso | Al mes (USD, aproximado) |
|---|---|
| App Service B1 | ~13 |
| PostgreSQL B1ms, 32 GB | 0 los primeros 12 meses (oferta gratuita, 750 h/mes) |
| Key Vault, VNet, DNS privado | < 1 |
| **Total** | **~13–15** |

Verificar en la calculadora y en «Cost Management» tras el primer día. El disco de
PostgreSQL tiene el crecimiento automático apagado para no salirse de la oferta.
El crédito de Azure for Students vence el **30/12/2026**: para seguir después hay
que renovar acreditando que se es estudiante.

## Qué cambió respecto del §5 original

| §5 original | Perfil sin gateway |
|---|---|
| Application Gateway con WAF como única IP pública | El App Service es la entrada pública; sin WAF |
| TLS en el gateway con certificado propio | TLS del App Service: `*.azurewebsites.net` o dominio propio con certificado administrado gratuito |
| Private endpoints para App Service, PostgreSQL y Key Vault | PostgreSQL en subred delegada (privado, gratis); Key Vault por service endpoint (gratis) |

Se mantiene: secretos en Key Vault (referencias, no valores), identidad
administrada, base sin acceso desde Internet, NSG 5432 sólo desde la app,
despliegue OIDC, respaldo de 7 días, WebJobs. La mitigación OWASP queda en la
aplicación (CSRF, cookies seguras, HSTS, hash de contraseñas, aislamiento por
almacén) y en la plataforma (HTTPS obligatorio, TLS 1.2, sin FTP).

## Otras decisiones

1. **Secretos como referencias a Key Vault** en la configuración del App Service
   (`@Microsoft.KeyVault(...)`); App Service los resuelve con su identidad.
2. **Migraciones, `check --deploy` y `collectstatic` al arrancar** la instancia: la
   base es privada y el runner de GitHub no llega a ella. Si fallan, la instancia
   no arranca.
3. **Scheduler: WebJobs del mismo App Service**. Horarios en `App_Data/LEEME.md`.
   **Verificar en el primer despliegue** que el job encuentra el entorno virtual:
   ejecutarlo a mano desde el portal (WebJobs → Run) y revisar su log.

## Despliegue paso a paso

Requisitos: Azure CLI (`winget install Microsoft.AzureCLI`) y `az bicep install`.

```powershell
az login

# 1. Regiones permitidas: Azure for Students restringe dónde se puede crear.
az policy assignment list --query "[].{nombre:displayName, parametros:parameters}" -o json
#    Elegir una de la lista (idealmente la más cercana a Chile).
az group create -n rg-tivoscanea -l <region-permitida>

# 2. Validar sin crear nada
$env:TIVOSCANEA_CLAVE_BD = "<clave larga generada>"     # no se guarda en el repo
$env:TIVOSCANEA_IP_ADMIN = (Invoke-RestMethod https://api.ipify.org)
az deployment group what-if -g rg-tivoscanea -f infra/main.bicep -p infra/main.bicepparam

# 3. Fase 1: todo, con el host *.azurewebsites.net
az deployment group create -g rg-tivoscanea -n main -f infra/main.bicep -p infra/main.bicepparam

# 4. Cargar la SECRET_KEY de Django (una vez)
$kv = az deployment group show -g rg-tivoscanea -n main --query properties.outputs.nombreKeyVault.value -o tsv
az role assignment create --role "Key Vault Secrets Officer" --assignee (az ad signed-in-user show --query id -o tsv) --scope (az keyvault show -n $kv --query id -o tsv)
az keyvault secret set --vault-name $kv -n django-secret-key --value (python -c "from django.core.management.utils import get_random_secret_key as g; print(g())")

# 5. Cerrar Key Vault a tu IP volviendo a desplegar sin ella
$env:TIVOSCANEA_IP_ADMIN = ""
az deployment group create -g rg-tivoscanea -n main -f infra/main.bicep -p infra/main.bicepparam
```

Después: crear el entorno `produccion` en GitHub (rama permitida: sólo `main`)
con las variables que lista `despliegue.yml`, completar `repositorio` en
`main.bicepparam`, y hacer merge a `main`. El primer arranque corre las
migraciones.

### Fase 2 (opcional): dominio propio

1. En el DNS del dominio: `CNAME app → <salida hostApp>` y
   `TXT asuid.app → <salida idVerificacionDominio>`. NIC Chile sólo delega:
   los registros van en un servicio de DNS (p. ej. Cloudflare, gratis).
2. Esperar a que propaguen y desplegar con
   `$env:TIVOSCANEA_DOMINIO = "app.tivoscanea.cl"` y
   `$env:TIVOSCANEA_ENLAZAR_DOMINIO = "true"`.

## Pendiente

- **Alta del primer almacén y su administrador en producción**: no hay pantalla
  de registro de almacenes; hoy sería `crear_almacen()` desde una consola SSH.
- **HSTS con subdominios y preload** (`security.W005`/`W021`): al tener dominio.
- **Monitoreo**: Application Insights no está en el §5.
- **Restauración probada**: el RTO de 4 h (§7) exige ensayar una restauración
  del respaldo de PostgreSQL al menos una vez.
