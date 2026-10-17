// PostgreSQL 16 Flexible Server con private endpoint y sin acceso público (§5).
// Respaldo automático con retención de 7 días (§7: RPO 24 h). Tier Burstable:
// suficiente para el piloto; se escala sin recrear el servidor.

param nombre string
param ubicacion string
param etiquetas object
param idSubredPrivada string
param idZonaDns string
param usuarioAdmin string
param nombreBaseDatos string

@secure()
param claveAdmin string

param sku string = 'Standard_B1ms'

resource servidor 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: nombre
  location: ubicacion
  tags: etiquetas
  sku: {
    name: sku
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: usuarioAdmin
    administratorLoginPassword: claveAdmin
    storage: {
      storageSizeGB: 32
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Disabled' }
  }
}

resource zonaHoraria 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: servidor
  name: 'timezone'
  // Las comparaciones de reloj de pared usan AT TIME ZONE explícito (§3); esto sólo
  // afecta lo que se ve en una consola psql.
  properties: { value: 'America/Santiago', source: 'user-override' }
}

resource baseDatos 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: servidor
  name: nombreBaseDatos
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

module endpoint 'endpoint-privado.bicep' = {
  name: 'pe-postgres'
  params: {
    nombre: 'pe-${nombre}'
    ubicacion: ubicacion
    etiquetas: etiquetas
    idSubred: idSubredPrivada
    idRecurso: servidor.id
    grupo: 'postgresqlServer'
    idZonaDns: idZonaDns
  }
}

output fqdn string = servidor.properties.fullyQualifiedDomainName
output nombreBaseDatos string = baseDatos.name
