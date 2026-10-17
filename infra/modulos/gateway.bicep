// Application Gateway WAF_v2: único componente con IP pública (§5). Termina TLS
// con el certificado guardado en Key Vault y reenvía al App Service por su private
// endpoint. WAF con reglas OWASP (Core Rule Set 3.2) en modo Prevención.
//
// Sin listener HTTP en el 80: el NSG sólo deja entrar el 443.

param nombre string
param ubicacion string
param etiquetas object
param idSubredGateway string
param hostApp string
param nombreKeyVault string
@description('URI del secreto del certificado en Key Vault, sin versión (se renueva solo).')
param idSecretoCertificado string

param capacidadMinima int = 1
param capacidadMaxima int = 2

resource ip 'Microsoft.Network/publicIPAddresses@2023-11-01' = {
  name: 'pip-${nombre}'
  location: ubicacion
  tags: etiquetas
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
  }
}

// El gateway lee el certificado de Key Vault con esta identidad.
resource identidad 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${nombre}'
  location: ubicacion
  tags: etiquetas
}

module accesoCertificado 'acceso-keyvault.bicep' = {
  name: 'acceso-kv-gateway'
  params: {
    nombreKeyVault: nombreKeyVault
    idPrincipal: identidad.properties.principalId
  }
}

resource waf 'Microsoft.Network/ApplicationGatewayWebApplicationFirewallPolicies@2023-11-01' = {
  name: 'waf-${nombre}'
  location: ubicacion
  tags: etiquetas
  properties: {
    policySettings: {
      state: 'Enabled'
      mode: 'Prevention'
      requestBodyCheck: true
      maxRequestBodySizeInKb: 128
      fileUploadLimitInMb: 1
    }
    managedRules: {
      managedRuleSets: [
        { ruleSetType: 'OWASP', ruleSetVersion: '3.2' }
      ]
    }
  }
}

var idGateway = resourceId('Microsoft.Network/applicationGateways', nombre)

resource gateway 'Microsoft.Network/applicationGateways@2023-11-01' = {
  name: nombre
  location: ubicacion
  tags: etiquetas
  dependsOn: [ accesoCertificado ]
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identidad.id}': {} }
  }
  properties: {
    sku: { name: 'WAF_v2', tier: 'WAF_v2' }
    autoscaleConfiguration: {
      minCapacity: capacidadMinima
      maxCapacity: capacidadMaxima
    }
    firewallPolicy: { id: waf.id }
    sslPolicy: {
      policyType: 'Predefined'
      policyName: 'AppGwSslPolicy20220101'
    }
    gatewayIPConfigurations: [
      { name: 'ipconfig', properties: { subnet: { id: idSubredGateway } } }
    ]
    frontendIPConfigurations: [
      { name: 'publica', properties: { publicIPAddress: { id: ip.id } } }
    ]
    frontendPorts: [
      { name: 'https', properties: { port: 443 } }
    ]
    sslCertificates: [
      { name: 'certificado', properties: { keyVaultSecretId: idSecretoCertificado } }
    ]
    backendAddressPools: [
      { name: 'app', properties: { backendAddresses: [ { fqdn: hostApp } ] } }
    ]
    probes: [
      {
        name: 'salud-app'
        properties: {
          protocol: 'Https'
          path: '/cuentas/login/'
          interval: 30
          timeout: 30
          unhealthyThreshold: 3
          pickHostNameFromBackendHttpSettings: true
          match: { statusCodes: [ '200-399' ] }
        }
      }
    ]
    backendHttpSettingsCollection: [
      {
        name: 'app-https'
        properties: {
          port: 443
          protocol: 'Https'
          cookieBasedAffinity: 'Disabled'
          // App Service enruta por el nombre *.azurewebsites.net.
          pickHostNameFromBackendAddress: true
          requestTimeout: 30
          probe: { id: '${idGateway}/probes/salud-app' }
        }
      }
    ]
    httpListeners: [
      {
        name: 'https'
        properties: {
          frontendIPConfiguration: { id: '${idGateway}/frontendIPConfigurations/publica' }
          frontendPort: { id: '${idGateway}/frontendPorts/https' }
          protocol: 'Https'
          sslCertificate: { id: '${idGateway}/sslCertificates/certificado' }
        }
      }
    ]
    requestRoutingRules: [
      {
        name: 'https-a-app'
        properties: {
          ruleType: 'Basic'
          priority: 100
          httpListener: { id: '${idGateway}/httpListeners/https' }
          backendAddressPool: { id: '${idGateway}/backendAddressPools/app' }
          backendHttpSettings: { id: '${idGateway}/backendHttpSettingsCollection/app-https' }
        }
      }
    ]
  }
}

output ipPublica string = ip.properties.ipAddress
