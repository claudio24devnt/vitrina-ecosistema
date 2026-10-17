# Infraestructura de TivoScanea en Azure (paquete 1.6)

Infraestructura como código (Bicep) de la arquitectura del §5 del brief.
**Todavía no se ha desplegado**: no hay suscripción. Compila y pasa el lint con
Bicep CLI 0.48.1 (2026-10-17), lo que valida sintaxis y propiedades contra los
esquemas de cada versión de API, pero no cuotas, nombres ocupados ni permisos:
antes del primer despliegue hay que correr `what-if` (abajo).

## Qué se crea

```
Internet ──443──▶ Application Gateway WAF_v2 (OWASP 3.2, Prevención, TLS)
                     │ IP pública: el único componente expuesto
                     ▼ 443 por private endpoint
              App Service Linux (Python 3.12, identidad administrada)
                     │ integración de red (route-all)
          ┌──────────┴───────────┐
          ▼ 5432 (PE)            ▼ 443 (PE)
   PostgreSQL 16 Flexible     Key Vault (RBAC)
   respaldo 7 días            db-password, django-secret-key, certificado TLS
```

| Archivo | Contenido |
|---|---|
| `main.bicep` | Orquesta los módulos; nombres únicos por grupo de recursos |
| `main.bicepparam` | Parámetros de producción, sin secretos |
| `modulos/red.bicep` | VNet, 3 subredes con NSG, zonas DNS privadas |
| `modulos/keyvault.bicep` | Key Vault con private endpoint |
| `modulos/postgres.bicep` | PostgreSQL 16 Flexible Server con private endpoint |
| `modulos/appservice.bicep` | Plan y App Service, referencias a Key Vault |
| `modulos/gateway.bicep` | Application Gateway WAF_v2 y política WAF |
| `modulos/oidc.bicep` | Identidad federada de GitHub Actions |
| `../.github/workflows/despliegue.yml` | Despliegue tras el CI en verde sobre `main` |

## Decisiones y desvíos respecto del brief (revisar)

1. **NSG del gateway no es «sólo 443»**. Azure exige abrir 65200-65535 desde
   `GatewayManager` y el sondeo de `AzureLoadBalancer` en la subred del
   Application Gateway v2; sin eso el recurso no se crea. Desde Internet, sólo 443.
2. **Secretos como referencias a Key Vault**. Las variables del App Service
   contienen `@Microsoft.KeyVault(...)`, no el valor: App Service lo resuelve con
   su identidad administrada. Interpreto que cumple «nunca en variables del App
   Service»; la alternativa (leer Key Vault desde Django) suma dos dependencias
   (`azure-identity`, `azure-keyvault-secrets`).
3. **El sitio SCM (Kudu) queda alcanzable desde Internet** para que GitHub
   Actions pueda desplegar, pero sin credenciales básicas: sólo acepta tokens de
   Entra ID (OIDC). El sitio de la aplicación rechaza todo lo que no llegue por el
   private endpoint. La alternativa estricta es un runner propio dentro de la VNet.
4. **Migraciones y `check --deploy` al arrancar** la instancia: la base es
   privada y el runner de GitHub no llega a ella. Si fallan, la instancia no
   arranca y el despliegue anterior sigue respondiendo.
5. **Host**: el gateway reenvía con el host `*.azurewebsites.net`; Django lo
   acepta en `ALLOWED_HOSTS` y el dominio público va en `CSRF_TRUSTED_ORIGINS`.
6. **Región**: `brazilsouth`. Hay región Chile Central; falta verificar que tenga
   Application Gateway WAF_v2 y PostgreSQL Flexible antes de cambiarla.
7. **Scheduler: WebJobs del mismo App Service** (decidido 2026-10-17). Sin
   recurso nuevo ni costo extra; corren en el mismo contenedor, con las mismas
   variables y la misma red. Horarios en `App_Data/LEEME.md`. Requieren *Always
   On* (plan Basic o superior) y `WEBSITE_SKIP_RUNNING_KUDUAGENT=false`.
   **Verificar en el primer despliegue** que el job encuentra el entorno virtual
   de la compilación: ejecutarlo a mano desde el portal y revisar su log.

## Costos aproximados (orden de magnitud, sin verificar contra la calculadora)

| Recurso | Aproximado al mes (USD) |
|---|---|
| Application Gateway WAF_v2 (costo fijo + 1 unidad) | 320–400 |
| App Service B1 | ~13 |
| PostgreSQL B1ms + 32 GB | ~20 |
| 3 private endpoints | ~22 |
| IP pública, Key Vault, DNS privado | ~5 |
| **Total** | **~380–460** |

El gateway es casi todo el costo. Con el crédito de Azure for Students (USD 100)
alcanza para menos de dos semanas. Para el piloto conviene decidirlo antes de
desplegar: mantenerlo sólo para la demostración ante el docente, o reemplazarlo
temporalmente (p. ej. Front Door Standard con WAF o restricciones de acceso del
propio App Service) y dejar el diseño del §5 documentado.

## Despliegue paso a paso

Requisitos: Azure CLI (`winget install Microsoft.AzureCLI`), Bicep
(`az bicep install`), un dominio y su certificado TLS en `.pfx`.

```powershell
az login
az group create -n rg-tivoscanea-prod -l brazilsouth

# Validar sin crear nada
az bicep build -f infra/main.bicep
$env:TIVOSCANEA_CLAVE_BD = "<clave larga generada>"     # no se guarda en el repo
$env:TIVOSCANEA_IP_ADMIN = (Invoke-RestMethod https://api.ipify.org)
az deployment group what-if -g rg-tivoscanea-prod -f infra/main.bicep -p infra/main.bicepparam

# Fase 1: todo menos el gateway
az deployment group create -g rg-tivoscanea-prod -f infra/main.bicep -p infra/main.bicepparam

# Darte permiso para escribir secretos (una vez) y cargarlos
$kv = az deployment group show -g rg-tivoscanea-prod -n main --query properties.outputs.nombreKeyVault.value -o tsv
az role assignment create --role "Key Vault Secrets Officer" --assignee (az ad signed-in-user show --query id -o tsv) --scope (az keyvault show -n $kv --query id -o tsv)
az role assignment create --role "Key Vault Certificates Officer" --assignee (az ad signed-in-user show --query id -o tsv) --scope (az keyvault show -n $kv --query id -o tsv)
az keyvault secret set --vault-name $kv -n django-secret-key --value (python -c "from django.core.management.utils import get_random_secret_key as g; print(g())")
az keyvault certificate import --vault-name $kv -n tivoscanea-tls -f certificado.pfx

# Fase 2: el gateway, y cerrar Key Vault a Internet
$env:TIVOSCANEA_FASE_GATEWAY = "true"
$env:TIVOSCANEA_IP_ADMIN = ""
az deployment group create -g rg-tivoscanea-prod -f infra/main.bicep -p infra/main.bicepparam
```

Después: apuntar el DNS del dominio a la salida `ipPublica`, crear el entorno
`produccion` en GitHub (rama permitida: sólo `main`) con las variables que
lista `despliegue.yml`, y hacer merge a `main`.

## Pendiente

- **HSTS con subdominios y preload** (`security.W005`/`W021`): se decide al
  tener el dominio definitivo. Es lo único que `check --deploy` deja pendiente.
- **Monitoreo**: Application Insights / Log Analytics no está en el §5.
- **Restauración probada**: el RTO de 4 h (§7) exige ensayar una restauración
  del respaldo de PostgreSQL al menos una vez.
