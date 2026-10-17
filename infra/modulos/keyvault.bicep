// Key Vault: único lugar donde viven los secretos (§5). Autorización por RBAC.
// La aplicación y el gateway llegan por el private endpoint; desde Internet sólo
// la IP del administrador, para cargar a mano el certificado TLS y
// `django-secret-key` (ver README). Con `ipAdministrador` vacío queda cerrado.
//
// `django-secret-key` NO se crea aquí, para que no pase por parámetros ni quede en
// el historial de despliegues.

param nombre string
param ubicacion string
param etiquetas object
param idSubredPrivada string
param idZonaDns string
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
    publicNetworkAccess: empty(ipAdministrador) ? 'Disabled' : 'Enabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      ipRules: empty(ipAdministrador) ? [] : [ { value: ipAdministrador } ]
    }
  }
}

resource secretoBd 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'db-password'
  properties: { value: claveBaseDatos }
}

module endpoint 'endpoint-privado.bicep' = {
  name: 'pe-keyvault'
  params: {
    nombre: 'pe-${nombre}'
    ubicacion: ubicacion
    etiquetas: etiquetas
    idSubred: idSubredPrivada
    idRecurso: kv.id
    grupo: 'vault'
    idZonaDns: idZonaDns
  }
}

output nombre string = kv.name
output id string = kv.id
output uri string = kv.properties.vaultUri
