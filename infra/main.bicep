// Infraestructura de TivoScanea en Azure (paquete 1.6, §5 del brief), perfil sin
// Application Gateway (decidido 2026-10-17 por costo). Se despliega a un grupo de
// recursos:
//
//   az deployment group create -g rg-tivoscanea -f infra/main.bicep \
//     -p infra/main.bicepparam
//
// Fase 1 crea todo con el host *.azurewebsites.net. Fase 2 (opcional), con el DNS
// del dominio ya apuntando, agrega el dominio propio y su certificado. Ver
// infra/README.md.

targetScope = 'resourceGroup'

@description('Prefijo corto de los nombres, en minúsculas.')
@maxLength(12)
param prefijo string = 'tivoscanea'

@description('Región. Azure for Students sólo permite algunas: ver README.')
param ubicacion string = resourceGroup().location

@description('Dominio propio, p. ej. app.tivoscanea.cl. Vacío = sólo *.azurewebsites.net.')
param dominio string = ''

@description('Fase 2: enlazar el dominio y emitir su certificado (exige el DNS listo).')
param enlazarDominio bool = false

@description('Repositorio de GitHub «usuario/repositorio» autorizado a desplegar.')
param repositorio string

@description('IP pública de quien administra, para cargar secretos en Key Vault. Vacía = cerrado.')
param ipAdministrador string = ''

@description('Correo para las alertas de monitoreo. Vacío = sin monitoreo.')
param correoAlertas string = ''

param usuarioBaseDatos string = 'tivoscanea_admin'

@secure()
@minLength(16)
param claveBaseDatos string

param etiquetas object = {
  proyecto: 'TivoScanea'
  entorno: 'produccion'
}

// Nombres globales únicos: Key Vault, App Service y PostgreSQL exponen un DNS.
var sufijo = take(uniqueString(resourceGroup().id), 6)
var nombreKeyVault = 'kv-${prefijo}-${sufijo}'
var nombreApp = 'app-${prefijo}-${sufijo}'
var nombrePostgres = 'psql-${prefijo}-${sufijo}'

module red 'modulos/red.bicep' = {
  name: 'red'
  params: {
    ubicacion: ubicacion
    prefijo: prefijo
    etiquetas: etiquetas
    nombrePostgres: nombrePostgres
  }
}

module keyVault 'modulos/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    nombre: nombreKeyVault
    ubicacion: ubicacion
    etiquetas: etiquetas
    idSubredApp: red.outputs.idSubredApp
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
    idSubredPostgres: red.outputs.idSubredPostgres
    idZonaDns: red.outputs.idZonaPostgres
    usuarioAdmin: usuarioBaseDatos
    claveAdmin: claveBaseDatos
    nombreBaseDatos: 'tivoscanea_db'
  }
}

module app 'modulos/appservice.bicep' = {
  name: 'appservice'
  params: {
    nombre: nombreApp
    ubicacion: ubicacion
    etiquetas: etiquetas
    idSubredApp: red.outputs.idSubredApp
    nombreKeyVault: keyVault.outputs.nombre
    hostBaseDatos: postgres.outputs.fqdn
    nombreBaseDatos: postgres.outputs.nombreBaseDatos
    usuarioBaseDatos: usuarioBaseDatos
    dominio: dominio
    enlazarDominio: enlazarDominio
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

module monitoreo 'modulos/monitoreo.bicep' = if (!empty(correoAlertas)) {
  name: 'monitoreo'
  params: {
    prefijo: prefijo
    nombreApp: app.outputs.nombre
    nombrePostgres: nombrePostgres
    correoAlertas: correoAlertas
    etiquetas: etiquetas
  }
}

output url string = 'https://${empty(dominio) ? app.outputs.hostPorDefecto : dominio}'
output nombreApp string = app.outputs.nombre
output nombreKeyVault string = keyVault.outputs.nombre
@description('Para el DNS del dominio: CNAME al host y TXT asuid con este valor.')
output hostApp string = app.outputs.hostPorDefecto
output idVerificacionDominio string = app.outputs.idVerificacionDominio
@description('Va en la variable AZURE_CLIENT_ID del entorno «produccion» de GitHub.')
output idClienteGithub string = oidc.outputs.idCliente
