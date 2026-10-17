// App Service Linux (Python 3.12) con identidad administrada (§5).
//
// Entrada: sólo por el private endpoint, desde el Application Gateway. El sitio
// principal rechaza todo lo demás (ipSecurityRestrictionsDefaultAction: Deny).
// El sitio de despliegue (SCM/Kudu) queda alcanzable desde GitHub Actions, pero
// sin credenciales de publicación: sólo acepta tokens de Entra ID (OIDC).
// Salida: integración de red con route-all, para llegar a PostgreSQL y Key Vault
// por sus private endpoints.
//
// Los secretos no están en la configuración: los valores son referencias a Key
// Vault que App Service resuelve con su identidad administrada.

param nombre string
param ubicacion string
param etiquetas object
param idSubredApp string
param idSubredPrivada string
param idZonaDns string
param nombreKeyVault string
param hostBaseDatos string
param nombreBaseDatos string
param usuarioBaseDatos string
param dominio string
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
    publicNetworkAccess: 'Enabled'
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      alwaysOn: true
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
      ipSecurityRestrictionsDefaultAction: 'Deny'
      scmIpSecurityRestrictionsUseMain: false
      scmIpSecurityRestrictionsDefaultAction: 'Allow'
      appSettings: [
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'DISABLE_COLLECTSTATIC', value: 'true' }
        { name: 'DJANGO_SECRET_KEY', value: '${referencia}django-secret-key)' }
        { name: 'DJANGO_DEBUG', value: 'False' }
        { name: 'DJANGO_PRODUCCION', value: 'True' }
        { name: 'DB_SSLMODE', value: 'require' }
        { name: 'DB_CONN_MAX_AGE', value: '60' }
        // El gateway reenvía con el host *.azurewebsites.net: ése es el que ve Django.
        // El dominio público llega en el Origin del navegador y se acepta por CSRF.
        { name: 'DJANGO_ALLOWED_HOSTS', value: '${nombre}.azurewebsites.net' }
        { name: 'DJANGO_CSRF_TRUSTED_ORIGINS', value: 'https://${dominio}' }
        { name: 'DB_HOST', value: hostBaseDatos }
        { name: 'DB_NAME', value: nombreBaseDatos }
        { name: 'DB_USER', value: usuarioBaseDatos }
        { name: 'DB_PASSWORD', value: '${referencia}db-password)' }
        { name: 'DB_PORT', value: '5432' }
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

module endpoint 'endpoint-privado.bicep' = {
  name: 'pe-app'
  params: {
    nombre: 'pe-${nombre}'
    ubicacion: ubicacion
    etiquetas: etiquetas
    idSubred: idSubredPrivada
    idRecurso: sitio.id
    grupo: 'sites'
    idZonaDns: idZonaDns
  }
}

output nombre string = sitio.name
output id string = sitio.id
output hostPorDefecto string = sitio.properties.defaultHostName
output idPrincipal string = sitio.identity.principalId
