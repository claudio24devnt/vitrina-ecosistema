// Correo saliente con Azure Communication Services (recuperación de contraseña).
//
// Sin SMTP: el tenant de la universidad no permite crear registros de aplicación en
// Entra ID, que es lo que exige el SMTP de ACS. La aplicación envía por la API REST
// con su identidad administrada (tivoscanea/correo_acs.py): no hay clave de correo.
//
// Dominio administrado por Azure (DoNotReply@<algo>.azurecomm.net): SÓLO PARA PRUEBAS.
// Microsoft lo limita a pocos correos por hora y no acepta aumentos de cuota; para
// producción hace falta un dominio propio verificado (SPF/DKIM).
//
// Se despliega solo, sin la clave de la base (como monitoreo.bicep):
//   az deployment group create -g rg-tivoscanea -n correo -f infra/modulos/correo.bicep `
//     -p prefijo=tivoscanea nombreApp=<app>

param prefijo string = 'tivoscanea'
param nombreApp string
@description('Dónde guarda ACS los datos de los correos.')
param ubicacionDatos string = 'Brazil'
param etiquetas object = {
  proyecto: 'TivoScanea'
  entorno: 'produccion'
}

var sufijo = take(uniqueString(resourceGroup().id), 6)

// Rol integrado que la documentación de ACS pide para enviar con Entra ID.
var rolCorreo = '09976791-48a7-449e-bb21-39d1a415f350' // Communication and Email Service Owner

resource app 'Microsoft.Web/sites@2023-12-01' existing = {
  name: nombreApp
}

resource servicioCorreo 'Microsoft.Communication/emailServices@2023-04-01' = {
  name: 'ecs-${prefijo}-${sufijo}'
  location: 'global'
  tags: etiquetas
  properties: { dataLocation: ubicacionDatos }
}

resource dominio 'Microsoft.Communication/emailServices/domains@2023-04-01' = {
  parent: servicioCorreo
  name: 'AzureManagedDomain'
  location: 'global'
  tags: etiquetas
  properties: {
    domainManagement: 'AzureManaged'
    userEngagementTracking: 'Disabled' // sin seguimiento de aperturas ni clics
  }
}

resource comunicacion 'Microsoft.Communication/communicationServices@2023-04-01' = {
  name: 'acs-${prefijo}-${sufijo}'
  location: 'global'
  tags: etiquetas
  properties: {
    dataLocation: ubicacionDatos
    linkedDomains: [ dominio.id ]
  }
}

resource permisoEnvio 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: comunicacion
  name: guid(comunicacion.id, app.id, rolCorreo)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', rolCorreo)
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Valor de ACS_ENDPOINT en el App Service.')
output endpoint string = 'https://${comunicacion.properties.hostName}'
@description('Valor de DEFAULT_FROM_EMAIL en el App Service.')
output remitente string = 'TivoScanea <DoNotReply@${dominio.properties.mailFromSenderDomain}>'
