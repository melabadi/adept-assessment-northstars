// Release · Microsoft: RequestHub hosted in Azure Container Apps, released through candidate revisions that get no
// traffic until they pass a gate. Deploy from this folder with `azd up`; remove everything with `azd down --purge`.
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

@description('GitHub repository (owner/name) whose release workflows sign in through OIDC. Set by the preprovision hook.')
param githubRepository string = ''

@description('OIDC subject prefix for repositories that use immutable subjects. Set by the preprovision hook.')
param githubOidcSubjectPrefix string = ''

var githubEnvironment = 'release-microsoft'
// The release workflows create revisions, move traffic, and deactivate revisions of the API container app.
// Container Apps Contributor covers exactly that: container apps only, no role assignments, no other resource types.
var containerAppsContributor = '358470bc-b998-42bd-ab17-a7e34c199c0f'
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
    githubRepository: githubRepository
    githubOidcSubjectPrefix: githubOidcSubjectPrefix
    githubEnvironment: githubEnvironment
    automationRoleDefinitionIds: [containerAppsContributor]
    tags: tags
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name
output GITHUB_ENVIRONMENT string = githubEnvironment

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
