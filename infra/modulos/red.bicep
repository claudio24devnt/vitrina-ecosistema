// Red virtual de TivoScanea (§5, perfil sin gateway, 2026-10-17). Dos subredes:
//   snet-app       integración de salida del App Service; con service endpoint a
//                  Key Vault, que sólo acepta tráfico de esta subred
//   snet-postgres  delegada a PostgreSQL Flexible (acceso privado, sin costo)
// y la zona DNS privada con la que la aplicación resuelve el servidor.
// Sin private endpoints ni gateway: no tienen costo fijo que pagar.

param ubicacion string
param prefijo string
param etiquetas object
param nombrePostgres string

var subredes = {
  app: '10.20.1.0/24'
  postgres: '10.20.3.0/24'
}

// Salida del App Service: no recibe tráfico entrante por esta subred.
resource nsgApp 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: 'nsg-${prefijo}-app'
  location: ubicacion
  tags: etiquetas
  properties: {
    securityRules: [
      {
        name: 'denegar-entrada'
        properties: {
          priority: 4000
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

// PostgreSQL: sólo el 5432 y sólo desde la subred de la aplicación.
resource nsgPostgres 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: 'nsg-${prefijo}-postgres'
  location: ubicacion
  tags: etiquetas
  properties: {
    securityRules: [
      {
        name: 'permitir-app-a-postgres'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: subredes.app
          sourcePortRange: '*'
          destinationAddressPrefix: subredes.postgres
          destinationPortRange: '5432'
        }
      }
      {
        name: 'denegar-resto-vnet'
        properties: {
          priority: 4000
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: 'vnet-${prefijo}'
  location: ubicacion
  tags: etiquetas
  properties: {
    addressSpace: { addressPrefixes: [ '10.20.0.0/16' ] }
    subnets: [
      {
        name: 'snet-app'
        properties: {
          addressPrefix: subredes.app
          networkSecurityGroup: { id: nsgApp.id }
          serviceEndpoints: [ { service: 'Microsoft.KeyVault' } ]
          delegations: [
            {
              name: 'app-service'
              properties: { serviceName: 'Microsoft.Web/serverFarms' }
            }
          ]
        }
      }
      {
        name: 'snet-postgres'
        properties: {
          addressPrefix: subredes.postgres
          networkSecurityGroup: { id: nsgPostgres.id }
          delegations: [
            {
              name: 'postgres'
              properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' }
            }
          ]
        }
      }
    ]
  }
}

// PostgreSQL con acceso privado exige una zona que termine en
// .postgres.database.azure.com, enlazada a la VNet antes de crear el servidor.
resource zonaPostgres 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: '${nombrePostgres}.private.postgres.database.azure.com'
  location: 'global'
  tags: etiquetas
}

resource enlaceZona 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: zonaPostgres
  name: 'enlace-${vnet.name}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

output idSubredApp string = vnet.properties.subnets[0].id
output idSubredPostgres string = vnet.properties.subnets[1].id
// Quien use esta salida espera al módulo completo, enlace incluido.
output idZonaPostgres string = zonaPostgres.id
