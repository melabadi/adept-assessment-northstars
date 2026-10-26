// The administrator resource name must be the principal's object id, which is only known at deploy time,
// so it lives in its own module.
param postgresName string
param principalId string
param principalName string
param principalType string = 'ServicePrincipal'

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' existing = {
  name: postgresName
}

resource admin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = {
  parent: postgres
  name: principalId
  properties: {
    principalType: principalType
    principalName: principalName
    tenantId: tenant().tenantId
  }
}
