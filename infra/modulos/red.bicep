// Red virtual de TivoScanea (§5). Cuatro subredes, cada una con su NSG:
//   snet-gateway  Application Gateway (único componente con IP pública)
//   snet-app      integración de red de salida del App Service
//   snet-privada  private endpoints (App Service, PostgreSQL, Key Vault)
// y las zonas DNS privadas para que los nombres resuelvan a IP internas.

param ubicacion string
param prefijo string
param etiquetas object

var espacio = '10.20.0.0/16'
var subredes = {
  gateway: '10.20.0.0/24'
  app: '10.20.1.0/24'
  privada: '10.20.2.0/24'
}

// Application Gateway v2: el 443 de Internet es el único tráfico de usuarios.
// Azure exige además 65200-65535 desde GatewayManager (administración del
// gateway) y el sondeo de AzureLoadBalancer; sin esas reglas el gateway no se crea.
resource nsgGateway 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: 'nsg-${prefijo}-gateway'
  location: ubicacion
  tags: etiquetas
  properties: {
    securityRules: [
      {
        name: 'permitir-https-internet'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '443'
        }
      }
      {
        name: 'permitir-administracion-gateway'
        properties: {
          priority: 110
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'GatewayManager'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '65200-65535'
        }
      }
      {
        name: 'permitir-sondeo-balanceador'
        properties: {
          priority: 120
          direction: 'Inbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: 'AzureLoadBalancer'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
      {
        name: 'denegar-resto-internet'
        properties: {
          priority: 4000
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

// Salida del App Service: no recibe tráfico entrante por esta subred.
resource nsgApp 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: 'nsg-${prefijo}-app'
  location: ubicacion
  tags: etiquetas
  properties: {
    securityRules: [
      {
        name: 'denegar-entrada-vnet'
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

// Private endpoints: al App Service sólo llega el gateway (443); a PostgreSQL sólo la
// subred de la aplicación (5432); al Key Vault, la aplicación y el gateway (443).
resource nsgPrivada 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: 'nsg-${prefijo}-privada'
  location: ubicacion
  tags: etiquetas
  properties: {
    securityRules: [
      {
        name: 'permitir-gateway-a-app-y-keyvault'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: subredes.gateway
          sourcePortRange: '*'
          destinationAddressPrefix: subredes.privada
          destinationPortRange: '443'
        }
      }
      {
        name: 'permitir-app-a-postgres'
        properties: {
          priority: 110
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: subredes.app
          sourcePortRange: '*'
          destinationAddressPrefix: subredes.privada
          destinationPortRange: '5432'
        }
      }
      {
        name: 'permitir-app-a-keyvault'
        properties: {
          priority: 120
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: subredes.app
          sourcePortRange: '*'
          destinationAddressPrefix: subredes.privada
          destinationPortRange: '443'
        }
      }
      {
        name: 'denegar-resto'
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

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: 'vnet-${prefijo}'
  location: ubicacion
  tags: etiquetas
  properties: {
    addressSpace: { addressPrefixes: [ espacio ] }
    subnets: [
      {
        name: 'snet-gateway'
        properties: {
          addressPrefix: subredes.gateway
          networkSecurityGroup: { id: nsgGateway.id }
        }
      }
      {
        name: 'snet-app'
        properties: {
          addressPrefix: subredes.app
          networkSecurityGroup: { id: nsgApp.id }
          delegations: [
            {
              name: 'app-service'
              properties: { serviceName: 'Microsoft.Web/serverFarms' }
            }
          ]
        }
      }
      {
        name: 'snet-privada'
        properties: {
          addressPrefix: subredes.privada
          networkSecurityGroup: { id: nsgPrivada.id }
          // Sin esto las NSG no se aplican a los private endpoints.
          privateEndpointNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

var zonas = [
  'privatelink.azurewebsites.net'
  'privatelink.postgres.database.azure.com'
  'privatelink.vaultcore.azure.net'
]

resource zonasDns 'Microsoft.Network/privateDnsZones@2020-06-01' = [for zona in zonas: {
  name: zona
  location: 'global'
  tags: etiquetas
}]

resource enlacesDns 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = [for (zona, i) in zonas: {
  parent: zonasDns[i]
  name: 'enlace-${vnet.name}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}]

output idSubredGateway string = vnet.properties.subnets[0].id
output idSubredApp string = vnet.properties.subnets[1].id
output idSubredPrivada string = vnet.properties.subnets[2].id
output idZonaWeb string = zonasDns[0].id
output idZonaPostgres string = zonasDns[1].id
output idZonaKeyVault string = zonasDns[2].id
