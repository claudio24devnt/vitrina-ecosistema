// Private endpoint con su registro en la zona DNS privada correspondiente.

param nombre string
param ubicacion string
param etiquetas object
param idSubred string
param idRecurso string
@description('Subrecurso del private link: sites, postgresqlServer o vault.')
param grupo string
param idZonaDns string

resource endpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: nombre
  location: ubicacion
  tags: etiquetas
  properties: {
    subnet: { id: idSubred }
    privateLinkServiceConnections: [
      {
        name: nombre
        properties: {
          privateLinkServiceId: idRecurso
          groupIds: [ grupo ]
        }
      }
    ]
  }
}

resource dns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'zona'
        properties: { privateDnsZoneId: idZonaDns }
      }
    ]
  }
}
