// Da a una identidad el rol «Key Vault Secrets User» (leer secretos) sobre el vault.

param nombreKeyVault string
param idPrincipal string

var rolLectorSecretos = '4633458b-17de-408a-b874-0445c86b69e6'

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: nombreKeyVault
}

resource acceso 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, idPrincipal, rolLectorSecretos)
  properties: {
    principalId: idPrincipal
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', rolLectorSecretos)
  }
}
