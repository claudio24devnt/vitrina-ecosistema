// App Service Linux (Python 3.12) con identidad administrada (§5, perfil sin
// gateway). Es la entrada pública: HTTPS obligatorio, TLS 1.2+, sin FTP ni
// credenciales de publicación (sólo Entra ID). Salida por integración de red con
// route-all, para llegar a PostgreSQL y Key Vault por la VNet.
//
// Los secretos no están en la configuración: los valores son referencias a Key
// Vault que App Service resuelve con su identidad administrada.
//
// Dominio propio (fase 2, opcional): con `enlazarDominio` se agrega el nombre y un
// certificado administrado gratuito de App Service. Antes hay que crear en el DNS
// el CNAME al host *.azurewebsites.net y el TXT asuid (ver README).

param nombre string
param ubicacion string
param etiquetas object
param idSubredApp string
param nombreKeyVault string
param hostBaseDatos string
param nombreBaseDatos string
param usuarioBaseDatos string
param dominio string = ''
param enlazarDominio bool = false
param sku string = 'B1'

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'asp-${nombre}'
  location: ubicacion
  tags: etiquetas
  kind: 'linux'
  sku: { name: sku }
  properties: { reserved: true }
}

var referencia = '@Microsoft.KeyVault(VaultName=${nombreKeyVault};SecretName='
var hostAzure = '${nombre}.azurewebsites.net'
var hosts = empty(dominio) ? hostAzure : '${hostAzure},${dominio}'
var origenes = empty(dominio) ? 'https://${hostAzure}' : 'https://${hostAzure},https://${dominio}'

resource sitio 'Microsoft.Web/sites@2023-12-01' = {
  name: nombre
  location: ubicacion
  tags: etiquetas
  kind: 'app,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    clientAffinityEnabled: false
    virtualNetworkSubnetId: idSubredApp
    vnetRouteAllEnabled: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      alwaysOn: true // lo exigen los WebJobs programados
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      http20Enabled: true
      healthCheckPath: '/cuentas/login/'
      // Al arrancar, con los secretos reales ya resueltos: check de despliegue (bloquea
      // la SECRET_KEY del CI, tivoscanea.E001) y migraciones, porque la base es privada
      // y el runner de GitHub no llega a ella. Si algo falla, la instancia no arranca.
      // collectstatic también va aquí y no en la compilación (Oryx), donde las
      // referencias a Key Vault podrían no estar resueltas todavía.
      appCommandLine: 'python manage.py check --deploy --fail-level ERROR && python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn tivoscanea.wsgi --bind=0.0.0.0:8000 --workers=2 --timeout=60'
      appSettings: [
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'DISABLE_COLLECTSTATIC', value: 'true' }
        // WebJobs (App_Data/jobs/triggered): en Linux necesitan el agente de Kudu, y
        // sus horarios se leen en hora de Chile y no en UTC.
        { name: 'WEBSITE_SKIP_RUNNING_KUDUAGENT', value: 'false' }
        { name: 'WEBSITE_TIME_ZONE', value: 'America/Santiago' }
        { name: 'DJANGO_SECRET_KEY', value: '${referencia}django-secret-key)' }
        { name: 'DJANGO_DEBUG', value: 'False' }
        { name: 'DJANGO_PRODUCCION', value: 'True' }
        { name: 'DJANGO_ALLOWED_HOSTS', value: hosts }
        { name: 'DJANGO_CSRF_TRUSTED_ORIGINS', value: origenes }
        { name: 'DB_HOST', value: hostBaseDatos }
        { name: 'DB_NAME', value: nombreBaseDatos }
        { name: 'DB_USER', value: usuarioBaseDatos }
        { name: 'DB_PASSWORD', value: '${referencia}db-password)' }
        { name: 'DB_PORT', value: '5432' }
        { name: 'DB_SSLMODE', value: 'require' }
        { name: 'DB_CONN_MAX_AGE', value: '60' }
      ]
    }
  }
}

// Sin usuario y contraseña de publicación (FTP ni Kudu): sólo Entra ID.
resource sinFtp 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: sitio
  name: 'ftp'
  properties: { allow: false }
}

resource sinScmBasico 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: sitio
  name: 'scm'
  properties: { allow: false }
}

// Fase 2: dominio propio con certificado administrado (gratuito, se renueva solo).
// El enlace se crea primero sin TLS, el certificado lo valida, y después se vuelve a
// declarar el enlace con SNI en un módulo (no se puede declarar dos veces aquí).
resource enlace 'Microsoft.Web/sites/hostNameBindings@2023-12-01' = if (enlazarDominio && !empty(dominio)) {
  parent: sitio
  name: dominio
  properties: {
    siteName: sitio.name
    hostNameType: 'Verified'
    sslState: 'Disabled'
  }
}

resource certificado 'Microsoft.Web/certificates@2023-12-01' = if (enlazarDominio && !empty(dominio)) {
  name: '${nombre}-${dominio}'
  location: ubicacion
  tags: etiquetas
  dependsOn: [ enlace ]
  properties: {
    serverFarmId: plan.id
    canonicalName: dominio
  }
}

module enlaceTls 'enlace-tls.bicep' = if (enlazarDominio && !empty(dominio)) {
  name: 'enlace-tls'
  params: {
    nombreSitio: sitio.name
    dominio: dominio
    huella: certificado!.properties.thumbprint
  }
}

output nombre string = sitio.name
output hostPorDefecto string = sitio.properties.defaultHostName
output idPrincipal string = sitio.identity.principalId
@description('Valor del registro TXT asuid.<dominio> que pide App Service para validar el dominio.')
output idVerificacionDominio string = sitio.properties.customDomainVerificationId
