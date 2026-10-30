// Operate · Microsoft: RequestHub hosted in Azure with an Azure Monitor alert on the notification worker's backlog and
// an Azure SRE Agent that investigates it, all in this solution's own resource group. Deploy from this folder with
// `azd up`; remove everything with `azd down --purge`.
targetScope = 'subscription'

@minLength(1)
@maxLength(24)
@description('azd environment name, for example ai-sdlc-operate. The resource group is rg-<name>.')
param environmentName string

@description('Region for the app, its database, monitoring, and the SRE Agent. PostgreSQL Flexible Server and Azure SRE Agent must both be available there for your subscription.')
param location string

@description('Object id of the person running azd. Receives every RequestHub app role and the SRE Agent Administrator role.')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@allowed(['MicrosoftFoundry', 'Anthropic'])
@description('Model provider for the SRE Agent. MicrosoftFoundry is Azure OpenAI; the agent picks the model for each task.')
param sreAgentModelProvider string = 'MicrosoftFoundry'

@description('The alert fires when the oldest pending notification is older than this, in seconds. A healthy worker stays under a few seconds.')
param backlogAgeThresholdSeconds int = 60

var tags = {
  'azd-env-name': environmentName
  solution: '07-operate-microsoft'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module app '../../../app/infra/requesthub.bicep' = {
  name: 'requesthub'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    principalId: principalId
    principalType: principalType
    // Nothing in GitHub signs in to Azure in this solution: the shared automation identity gets no federated
    // credential, no app roles, and no registry access.
    automationCanPushImages: false
    automationAppRoleNames: []
    tags: tags
  }
}

module monitoring 'monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: {
    location: location
    appInsightsName: app.outputs.appInsightsName
    logAnalyticsName: app.outputs.logAnalyticsName
    workerAppName: app.outputs.workerAppName
    backlogAgeThresholdSeconds: backlogAgeThresholdSeconds
    tags: tags
  }
}

module sreAgent 'sre-agent.bicep' = {
  name: 'sre-agent'
  scope: rg
  params: {
    agentName: 'sre-${environmentName}'
    location: location
    workloadAppInsightsName: app.outputs.appInsightsName
    logAnalyticsName: app.outputs.logAnalyticsName
    modelProvider: sreAgentModelProvider
    presenterPrincipalId: principalId
    presenterPrincipalType: principalType
    tags: tags
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name

// Read by app/infra/api.parameters.json and worker.parameters.json when `azd deploy` ships the container apps.
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = app.outputs.registryLoginServer
output AZURE_CONTAINER_REGISTRY_NAME string = app.outputs.registryName
output AZURE_CONTAINER_ENVIRONMENT_NAME string = app.outputs.containerAppsEnvironmentName
output APP_IDENTITY_ID string = app.outputs.appIdentityId
output APP_IDENTITY_CLIENT_ID string = app.outputs.appIdentityClientId
output APP_IDENTITY_NAME string = app.outputs.appIdentityName
output APPLICATIONINSIGHTS_CONNECTION_STRING string = app.outputs.appInsightsConnectionString
output POSTGRES_HOST string = app.outputs.postgresHost
output POSTGRES_DATABASE string = app.outputs.postgresDatabase
output STORAGE_BLOB_ENDPOINT string = app.outputs.storageBlobEndpoint
output API_APP_NAME string = app.outputs.apiAppName
output WORKER_APP_NAME string = app.outputs.workerAppName
output API_URL string = app.outputs.apiUrl
output API_CLIENT_ID string = app.outputs.apiClientId
output API_IDENTIFIER_URI string = app.outputs.apiIdentifierUri
output AUTOMATION_CLIENT_ID string = app.outputs.automationClientId

// Read by configure_sre_agent.py and incident.py.
output APPLICATIONINSIGHTS_NAME string = app.outputs.appInsightsName
output LOG_ANALYTICS_NAME string = app.outputs.logAnalyticsName
output BACKLOG_ALERT_NAME string = monitoring.outputs.alertName
output BACKLOG_ALERT_THRESHOLD_SECONDS int = backlogAgeThresholdSeconds
output WORKBOOK_ID string = monitoring.outputs.workbookId
output SRE_AGENT_NAME string = sreAgent.outputs.agentName
output SRE_AGENT_PORTAL_URL string = sreAgent.outputs.portalUrl
