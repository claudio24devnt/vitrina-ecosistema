// Parámetros del despliegue de producción. No contiene secretos: la clave de la
// base de datos se pide por variable de entorno al desplegar (ver README).
using 'main.bicep'

param prefijo = 'tivoscanea'
param ubicacion = 'brazilsouth' // la región más cercana a Chile con todos los servicios
param dominio = 'app.tivoscanea.cl' // PENDIENTE: dominio real
param repositorio = 'PENDIENTE/vitrina-ecosistema' // PENDIENTE: usuario/repositorio en GitHub
param claveBaseDatos = readEnvironmentVariable('TIVOSCANEA_CLAVE_BD')
param ipAdministrador = readEnvironmentVariable('TIVOSCANEA_IP_ADMIN', '')
param desplegarGateway = bool(readEnvironmentVariable('TIVOSCANEA_FASE_GATEWAY', 'false'))
