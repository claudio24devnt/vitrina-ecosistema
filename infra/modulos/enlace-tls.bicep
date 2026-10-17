// Activa TLS (SNI) en el enlace del dominio propio con el certificado administrado.
// Va en un módulo aparte porque el mismo enlace ya se declaró sin TLS para que el
// certificado pudiera validarse.

param nombreSitio string
param dominio string
param huella string

resource sitio 'Microsoft.Web/sites@2023-12-01' existing = {
  name: nombreSitio
}

resource enlace 'Microsoft.Web/sites/hostNameBindings@2023-12-01' = {
  parent: sitio
  name: dominio
  properties: {
    siteName: nombreSitio
    hostNameType: 'Verified'
    sslState: 'SniEnabled'
    thumbprint: huella
  }
}
