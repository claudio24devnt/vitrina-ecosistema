// Presupuesto mensual del grupo de recursos con aviso por correo (mismo grupo de
// acciones que el monitoreo). Con Azure for Students, si el crédito se acaba la
// suscripción se deshabilita y la aplicación deja de responder: este aviso llega
// antes. Gasto medido: ~USD 0,45/día (~USD 14/mes, noviembre 2026).
//
// No cuesta nada. Se despliega solo:
//   az deployment group create -g rg-tivoscanea -n presupuesto -f infra/modulos/presupuesto.bicep

param prefijo string = 'tivoscanea'
@description('Tope mensual en USD. El gasto normal es ~14; 20 deja margen para la restauración de prueba o un pico.')
param montoMensual int = 20
@description('Primer día del mes desde el que rige (no puede ser anterior al mes en curso).')
param inicio string = '2026-11-01'

resource avisos 'Microsoft.Insights/actionGroups@2023-01-01' existing = {
  name: 'ag-${prefijo}'
}

resource presupuesto 'Microsoft.Consumption/budgets@2023-05-01' = {
  name: 'presupuesto-${prefijo}'
  properties: {
    category: 'Cost'
    amount: montoMensual
    timeGrain: 'Monthly'
    timePeriod: { startDate: inicio }
    notifications: {
      gastoReal80: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 80
        thresholdType: 'Actual'
        contactGroups: [ avisos.id ]
        contactEmails: []
      }
      pronostico100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Forecasted'
        contactGroups: [ avisos.id ]
        contactEmails: []
      }
    }
  }
}
