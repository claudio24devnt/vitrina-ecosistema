// Infraestructura de TivoScanea en Azure (paquete 1.6, §5 del brief).
// Se despliega a un grupo de recursos:
//
//   az deployment group create -g rg-tivoscanea-prod -f infra/main.bicep \
//     -p infra/main.bicepparam
//
// En dos fases (ver infra/README.md): la primera con desplegarGateway=false crea
// todo menos el gateway; se cargan a mano el certificado y la SECRET_KEY en Key
// Vault; la segunda, con true, crea el gateway que usa ese certificado.

targetScope = 'resourceGroup'

@description('Prefijo corto de los nombres, en minúsculas.')
@maxLength(12)
param prefijo string = 'tivoscanea'

param ubicacion string = resourceGroup().location

@description('Dominio público del sistema, p. ej. app.tivoscanea.cl.')
param dominio string

@description('Repositorio de GitHub «usuario/repositorio» autorizado a desplegar.')
param repositorio string

@description('Nombre del certificado TLS importado en Key Vault.')
param nombreCertificado string = 'tivoscanea-tls'

@description('Fase 2: crear el Application Gateway (exige el certificado ya cargado).')
param desplegarGateway bool = false

@description('IP pública de quien administra, para cargar secretos en Key Vault. Vacía = cerrado.')
param ipAdministrador string = ''

param usuarioBaseDatos string = 'tivoscanea_admin'

@secure()
@minLength(16)
param claveBaseDatos string

param etiquetas object = {
  proyecto: 'TivoScanea'
  entorno: 'produccion'
}

// Nombres globales únicos: Key Vault, App Service y PostgreSQL exponen un DNS.
var sufijo = uniqueString(resourceGroup().id)
var nombreKeyVault = 'kv-${prefijo}-${take(sufijo, 6)}'
var nombreApp = 'app-${prefijo}-${take(sufijo, 6)}'
var nombrePostgres = 'psql-${prefijo}-${take(sufijo, 6)}'
var nombreBaseDatos = 'tivoscanea_db'

module red 'modulos/red.bicep' = {
  name: 'red'
  params: {
    ubicacion: ubicacion
    prefijo: prefijo
    etiquetas: etiquetas
  }
}

module keyVault 'modulos/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    nombre: nombreKeyVault
    ubicacion: ubicacion
    etiquetas: etiquetas
    idSubredPrivada: red.outputs.idSubredPrivada
    idZonaDns: red.outputs.idZonaKeyVault
    ipAdministrador: ipAdministrador
    claveBaseDatos: claveBaseDatos
  }
}

module postgres 'modulos/postgres.bicep' = {
  name: 'postgres'
  params: {
    nombre: nombrePostgres
    ubicacion: ubicacion
    etiquetas: etiquetas
    idSubredPrivada: red.outputs.idSubredPrivada
    idZonaDns: red.outputs.idZonaPostgres
    usuarioAdmin: usuarioBaseDatos
    claveAdmin: claveBaseDatos
    nombreBaseDatos: nombreBaseDatos
  }
}

module app 'modulos/appservice.bicep' = {
  name: 'appservice'
  params: {
    nombre: nombreApp
    ubicacion: ubicacion
    etiquetas: etiquetas
    idSubredApp: red.outputs.idSubredApp
    idSubredPrivada: red.outputs.idSubredPrivada
    idZonaDns: red.outputs.idZonaWeb
    nombreKeyVault: keyVault.outputs.nombre
    hostBaseDatos: postgres.outputs.fqdn
    nombreBaseDatos: postgres.outputs.nombreBaseDatos
    usuarioBaseDatos: usuarioBaseDatos
    dominio: dominio
  }
}

// La aplicación lee sus secretos de Key Vault con su identidad administrada.
module appLeeSecretos 'modulos/acceso-keyvault.bicep' = {
  name: 'acceso-kv-app'
  params: {
    nombreKeyVault: keyVault.outputs.nombre
    idPrincipal: app.outputs.idPrincipal
  }
}

module gateway 'modulos/gateway.bicep' = if (desplegarGateway) {
  name: 'gateway'
  params: {
    nombre: 'agw-${prefijo}'
    ubicacion: ubicacion
    etiquetas: etiquetas
    idSubredGateway: red.outputs.idSubredGateway
    hostApp: app.outputs.hostPorDefecto
    nombreKeyVault: keyVault.outputs.nombre
    uriCertificado: '${keyVault.outputs.uri}secrets/${nombreCertificado}'
  }
}

module oidc 'modulos/oidc.bicep' = {
  name: 'oidc'
  params: {
    nombre: 'id-${prefijo}-github'
    ubicacion: ubicacion
    etiquetas: etiquetas
    repositorio: repositorio
    nombreApp: app.outputs.nombre
  }
}

output ipPublica string = desplegarGateway ? gateway!.outputs.ipPublica : 'fase 1: sin gateway'
output nombreApp string = app.outputs.nombre
output nombreKeyVault string = keyVault.outputs.nombre
@description('Va en la variable AZURE_CLIENT_ID del entorno «produccion» de GitHub.')
output idClienteGithub string = oidc.outputs.idCliente
