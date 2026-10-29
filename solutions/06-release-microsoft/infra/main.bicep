// Release · Microsoft: RequestHub hosted in Azure Container Apps, released through candidate revisions that get no
// traffic until a person promotes them. The release runs in Azure: a push to the registry fires Event Grid, a Logic App
// starts the release job, and Container Apps jobs gate, promote, abort, roll back, and rehearse a bad release.
// Deploy from this folder with `azd up`; remove everything with `azd down --purge`.
targetScope = 'subscription'

@minLength(1)
@maxLength(24)
@description('azd environment name, for example ai-sdlc-release. The resource group is rg-<name>.')
param environmentName string

@description('Region for the app, its database, and monitoring. PostgreSQL Flexible Server must be allowed there for your subscription.')
param location string

@description('Object id of the person running azd. Receives every RequestHub app role.')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

// The release jobs create revisions, move traffic, and deactivate revisions of the API container app: Container Apps
// Contributor covers exactly that (container apps only, no role assignments, no other resource types). They also read
// the release jobs' executions, so that one release step runs at a time: Container Apps Jobs Reader, read-only.
var containerAppsContributor = '358470bc-b998-42bd-ab17-a7e34c199c0f'
var containerAppsJobsReader = 'edd66693-d32a-450b-997d-0158c03976b0'
var tags = {
  'azd-env-name': environmentName
  solution: '06-release-microsoft'
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
    // The automation identity runs the release jobs. It pulls their image (AcrPull, granted in release.bicep) and
    // never pushes: images are built by Azure Container Registry itself.
    automationRoleDefinitionIds: [containerAppsContributor, containerAppsJobsReader]
    automationCanPushImages: false
    tags: tags
  }
}

module release 'release.bicep' = {
  name: 'release'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    tags: tags
    registryName: app.outputs.registryName
    automationPrincipalId: app.outputs.automationPrincipalId
    logAnalyticsId: app.outputs.logAnalyticsId
    apiAppName: app.outputs.apiAppName
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_SUBSCRIPTION_ID string = subscription().subscriptionId
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

// Read by infra/jobs.parameters.json when `azd deploy release` ships the release jobs.
output AUTOMATION_IDENTITY_ID string = resourceId(subscription().subscriptionId, rg.name, 'Microsoft.ManagedIdentity/userAssignedIdentities', app.outputs.automationIdentityName)
output RELEASE_TRIGGER_PRINCIPAL_ID string = release.outputs.triggerPrincipalId
output RELEASE_TRIGGER_NAME string = release.outputs.triggerName
output RELEASE_WORKBOOK_ID string = release.outputs.workbookId
output LOG_ANALYTICS_WORKSPACE_ID string = app.outputs.logAnalyticsCustomerId
