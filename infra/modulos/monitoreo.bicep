// Monitoreo mínimo (pendiente de 1.6): alertas por correo con métricas que Azure ya
// recoge gratis del App Service y de PostgreSQL. Sin Application Insights ni pruebas
// de disponibilidad (cobran por ejecución). Costo: ~USD 0,10 al mes por regla; los
// correos del grupo de acciones son gratis.
//
// Usa recursos que ya existen, así que se puede desplegar solo, sin la clave de la
// base de datos (ver infra/README.md).

param prefijo string
param nombreApp string
param nombrePostgres string

@description('Correo que recibe las alertas.')
param correoAlertas string

param etiquetas object = {
  proyecto: 'TivoScanea'
  entorno: 'produccion'
}

resource app 'Microsoft.Web/sites@2023-12-01' existing = {
  name: nombreApp
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' existing = {
  name: nombrePostgres
}

resource grupo 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-${prefijo}'
  location: 'global'
  tags: etiquetas
  properties: {
    groupShortName: take(prefijo, 12)
    enabled: true
    emailReceivers: [
      {
        name: 'operador'
        emailAddress: correoAlertas
        useCommonAlertSchema: true
      }
    ]
  }
}

// Una regla por señal. `ventana` es el período que se evalúa; `cada`, cada cuánto.
var reglas = [
  {
    nombre: 'app-sin-salud'
    descripcion: 'TivoScanea no responde en /salud/: la aplicación está caída o reiniciándose.'
    severidad: 1
    recurso: app.id
    espacio: 'Microsoft.Web/sites'
    metrica: 'HealthCheckStatus'
    agregacion: 'Average'
    operador: 'LessThan'
    umbral: 100
    cada: 'PT5M'
    ventana: 'PT15M'
  }
  {
    nombre: 'app-errores-5xx'
    descripcion: 'TivoScanea respondió más de 5 errores del servidor (5xx) en 15 minutos.'
    severidad: 2
    recurso: app.id
    espacio: 'Microsoft.Web/sites'
    metrica: 'Http5xx'
    agregacion: 'Total'
    operador: 'GreaterThan'
    umbral: 5
    cada: 'PT5M'
    ventana: 'PT15M'
  }
  {
    nombre: 'bd-caida'
    descripcion: 'La base de datos PostgreSQL no está disponible.'
    severidad: 0
    recurso: postgres.id
    espacio: 'Microsoft.DBforPostgreSQL/flexibleServers'
    metrica: 'is_db_alive'
    agregacion: 'Maximum'
    operador: 'LessThan'
    umbral: 1
    cada: 'PT5M'
    ventana: 'PT15M'
  }
  {
    // El disco no crece solo (postgres.bicep): avisar antes de que se llene.
    nombre: 'bd-disco'
    descripcion: 'El disco de PostgreSQL pasó el 80 %. Hay que agrandarlo a mano.'
    severidad: 2
    recurso: postgres.id
    espacio: 'Microsoft.DBforPostgreSQL/flexibleServers'
    metrica: 'storage_percent'
    agregacion: 'Average'
    operador: 'GreaterThan'
    umbral: 80
    cada: 'PT1H'
    ventana: 'PT6H'
  }
]

resource alertas 'Microsoft.Insights/metricAlerts@2018-03-01' = [
  for regla in reglas: {
    name: 'alerta-${prefijo}-${regla.nombre}'
    location: 'global'
    tags: etiquetas
    properties: {
      description: regla.descripcion
      severity: regla.severidad
      enabled: true
      scopes: [regla.recurso]
      evaluationFrequency: regla.cada
      windowSize: regla.ventana
      autoMitigate: true
      criteria: {
        'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
        allOf: [
          {
            criterionType: 'StaticThresholdCriterion'
            name: regla.metrica
            metricNamespace: regla.espacio
            metricName: regla.metrica
            timeAggregation: regla.agregacion
            operator: regla.operador
            threshold: regla.umbral
          }
        ]
      }
      actions: [
        {
          actionGroupId: grupo.id
        }
      ]
    }
  }
]

output alertas array = [for (regla, i) in reglas: alertas[i].name]
