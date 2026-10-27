// Develop · Microsoft: RequestHub hosted in Azure with its triage panel backed by a Microsoft Foundry agent, in this
// solution's own resource group. Deploy from this folder with `azd up`; remove everything with `azd down --purge`.
targetScope = 'subscription'

@minLength(1)
@maxLength(24)
@description('azd environment name, for example ai-sdlc-develop. The resource group is rg-<name>.')
param environmentName string

@description('Region for the app, its database, and monitoring. PostgreSQL Flexible Server must be allowed there for your subscription.')
param location string

@description('Region for Microsoft Foundry. The model below must be available there.')
param aiLocation string = 'eastus2'

@description('Object id of the person running azd. Receives every RequestHub app role and the Foundry User role.')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@description('GitHub repository (owner/name) whose workflows publish and evaluate the agent through OIDC. Set by the preprovision hook.')
param githubRepository string = ''

@description('OIDC subject prefix for repositories that use immutable subjects. Set by the preprovision hook.')
param githubOidcSubjectPrefix string = ''

@description('Chat model for the triage agent. triage-agent.yaml sets temperature, so pick a non-reasoning model.')
param modelName string = 'gpt-4.1-mini'
param modelVersion string = '2025-04-14'

@description('Model capacity in thousands of tokens per minute.')
param modelCapacity int = 50

@description('Name of the Foundry agent the app calls. publish_triage_agent.py publishes it.')
param triageAgentName string = 'requesthub-triage'

var githubEnvironment = 'develop-microsoft'
var tags = {
  'azd-env-name': environmentName
  solution: '03-develop-microsoft'
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
    tags: tags
  }
}

module foundry 'foundry.bicep' = {
  name: 'foundry'
  scope: rg
  params: {
    environmentName: environmentName
    location: aiLocation
    modelName: modelName
    modelVersion: modelVersion
    modelCapacity: modelCapacity
    users: [
      { principalId: principalId, principalType: principalType }
      { principalId: app.outputs.appIdentityPrincipalId, principalType: 'ServicePrincipal' }
      { principalId: app.outputs.automationPrincipalId, principalType: 'ServicePrincipal' }
    ]
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
output TRIAGE_PROVIDER string = 'Foundry'
output TRIAGE_AGENT_NAME string = triageAgentName

output FOUNDRY_ACCOUNT_NAME string = foundry.outputs.accountName
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output FOUNDRY_MODEL_DEPLOYMENT string = foundry.outputs.modelDeployment
