// Identidad con la que GitHub Actions despliega, sin secretos (§5): credencial
// federada OIDC limitada al entorno «produccion» del repositorio (que en GitHub
// sólo admite la rama main) y rol Website Contributor sólo sobre el App Service.

param nombre string
param ubicacion string
param etiquetas object
param repositorio string // «usuario/repositorio» en GitHub
param nombreApp string

resource identidad 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: nombre
  location: ubicacion
  tags: etiquetas
}

resource federada 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: identidad
  name: 'github-produccion'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    // El job de despliegue declara `environment: produccion`; GitHub firma el token
    // con este sujeto y Azure no acepta tokens de otras ramas ni de pull requests.
    subject: 'repo:${repositorio}:environment:produccion'
    audiences: [ 'api://AzureADTokenExchange' ]
  }
}

resource app 'Microsoft.Web/sites@2023-12-01' existing = {
  name: nombreApp
}

var rolWebsiteContributor = 'de139f84-1756-47ae-9be6-808fbbe84772'

resource permiso 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: app
  name: guid(app.id, identidad.id, rolWebsiteContributor)
  properties: {
    principalId: identidad.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', rolWebsiteContributor)
  }
}

output idCliente string = identidad.properties.clientId
