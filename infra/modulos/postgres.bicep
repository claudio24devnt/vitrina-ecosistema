// PostgreSQL 16 Flexible Server con acceso privado: vive en una subred delegada de
// la VNet y no tiene dirección pública (§5). Respaldo automático de 7 días (§7:
// RPO 24 h).
//
// B1ms con 32 GB es lo que cubre la oferta gratuita de 12 meses de Azure (750 h al
// mes). El crecimiento automático del disco queda apagado para no salirse de ella
// sin darse cuenta: si se llena, hay que subirlo a mano.

param nombre string
param ubicacion string
param etiquetas object
param idSubredPostgres string
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
      autoGrow: 'Disabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
    network: {
      delegatedSubnetResourceId: idSubredPostgres
      privateDnsZoneArmResourceId: idZonaDns
      publicNetworkAccess: 'Disabled'
    }
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

output fqdn string = servidor.properties.fullyQualifiedDomainName
output nombreBaseDatos string = baseDatos.name
