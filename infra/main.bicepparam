// Parámetros del despliegue. No contiene secretos: la clave de la base de datos se
// pide por variable de entorno al desplegar (ver README).
using 'main.bicep'

param prefijo = 'tivoscanea'
// La región la define el grupo de recursos (az group create -l ...): ver README.
param repositorio = 'claudio24devnt/vitrina-ecosistema'
param dominio = readEnvironmentVariable('TIVOSCANEA_DOMINIO', '')
param enlazarDominio = bool(readEnvironmentVariable('TIVOSCANEA_ENLAZAR_DOMINIO', 'false'))
param claveBaseDatos = readEnvironmentVariable('TIVOSCANEA_CLAVE_BD')
param ipAdministrador = readEnvironmentVariable('TIVOSCANEA_IP_ADMIN', '')
