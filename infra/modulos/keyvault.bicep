// Key Vault: único lugar donde viven los secretos (§5). Autorización por RBAC.
// Desde la red sólo entran la subred de la aplicación (service endpoint, sin
// costo) y, si se indica, la IP de quien administra, para cargar a mano
// `django-secret-key` (ver README).
//
// `django-secret-key` NO se crea aquí, para que no pase por parámetros ni quede en
// el historial de despliegues.

param nombre string
param ubicacion string
param etiquetas object
param idSubredApp string
param ipAdministrador string = ''

@secure()
param claveBaseDatos string

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: nombre
  location: ubicacion
  tags: etiquetas
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 30
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      virtualNetworkRules: [ { id: idSubredApp } ]
      ipRules: empty(ipAdministrador) ? [] : [ { value: ipAdministrador } ]
    }
  }
}

resource secretoBd 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'db-password'
  properties: { value: claveBaseDatos }
}

output nombre string = kv.name
