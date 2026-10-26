// Shared Azure baseline for every Microsoft-track demo. Provisioned once with `azd provision`.
targetScope = 'subscription'

@minLength(1)
@maxLength(24)
@description('azd environment name. Used for the resource group (rg-<name>) and resource naming.')
param environmentName string

@description('Region for the app, database, networking, monitoring, and load testing. Must allow PostgreSQL Flexible Server for your subscription.')
param location string

@description('Region for Microsoft Foundry.')
param aiLocation string = location

@description('Region for Azure AI Search (capacity varies by region).')
param searchLocation string = location

@description('Object id of the person running azd. Receives every RequestHub app role and the data-plane roles needed by the demos.')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@description('GitHub repository (owner/name) allowed to sign in to Azure with OIDC. Leave empty to skip the federated credentials.')
param githubRepository string = ''

@description('Subject prefix of the repository\'s GitHub OIDC tokens. Repositories that use immutable subjects need it: gh api repos/OWNER/REPO/actions/oidc/customization/sub --jq .sub_claim_prefix')
param githubOidcSubjectPrefix string = ''

@description('Chat model deployed to Foundry for all agent demos.')
param modelName string = 'gpt-4.1-mini'
param modelVersion string = '2025-04-14'
@description('Model capacity in thousands of tokens per minute.')
param modelCapacity int = 50

@description('Storage shared-key access. Secure phase (Microsoft track) remediates this posture gap by setting it to false.')
param storageAllowSharedKeyAccess bool = true

@description('PostgreSQL major version.')
param postgresVersion string = '16'

var tags = {
  'azd-env-name': environmentName
  workload: 'ai-sdlc-requesthub'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module core 'core.bicep' = {
  name: 'requesthub-core'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    aiLocation: aiLocation
    searchLocation: searchLocation
    principalId: principalId
    principalType: principalType
    githubRepository: githubRepository
    githubOidcSubjectPrefix: githubOidcSubjectPrefix
    modelName: modelName
    modelVersion: modelVersion
    modelCapacity: modelCapacity
    storageAllowSharedKeyAccess: storageAllowSharedKeyAccess
    postgresVersion: postgresVersion
    tags: tags
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = core.outputs.registryLoginServer
output AZURE_CONTAINER_REGISTRY_NAME string = core.outputs.registryName
output AZURE_CONTAINER_ENVIRONMENT_NAME string = core.outputs.containerAppsEnvironmentName
output APP_IDENTITY_ID string = core.outputs.appIdentityId
output APP_IDENTITY_CLIENT_ID string = core.outputs.appIdentityClientId
output APP_IDENTITY_NAME string = core.outputs.appIdentityName
output AUTOMATION_CLIENT_ID string = core.outputs.automationClientId
output AUTOMATION_PRINCIPAL_ID string = core.outputs.automationPrincipalId
output APPLICATIONINSIGHTS_CONNECTION_STRING string = core.outputs.appInsightsConnectionString
output APPLICATIONINSIGHTS_NAME string = core.outputs.appInsightsName
output LOG_ANALYTICS_WORKSPACE_NAME string = core.outputs.logAnalyticsName
output LOG_ANALYTICS_WORKSPACE_ID string = core.outputs.logAnalyticsCustomerId
output POSTGRES_HOST string = core.outputs.postgresHost
output POSTGRES_DATABASE string = core.outputs.postgresDatabase
output STORAGE_ACCOUNT_NAME string = core.outputs.storageAccountName
output STORAGE_BLOB_ENDPOINT string = core.outputs.storageBlobEndpoint
output API_APP_NAME string = core.outputs.apiAppName
output WORKER_APP_NAME string = core.outputs.workerAppName
output API_URL string = core.outputs.apiUrl
output API_CLIENT_ID string = core.outputs.apiClientId
output API_IDENTIFIER_URI string = core.outputs.apiIdentifierUri
output FOUNDRY_ACCOUNT_NAME string = core.outputs.foundryAccountName
output FOUNDRY_PROJECT_NAME string = core.outputs.foundryProjectName
output FOUNDRY_PROJECT_ENDPOINT string = core.outputs.foundryProjectEndpoint
output FOUNDRY_MODEL_DEPLOYMENT string = core.outputs.foundryModelDeployment
output SEARCH_SERVICE_NAME string = core.outputs.searchName
output SEARCH_ENDPOINT string = core.outputs.searchEndpoint
output SEARCH_CONNECTION_NAME string = core.outputs.searchConnectionName
output LOAD_TEST_NAME string = core.outputs.loadTestName
