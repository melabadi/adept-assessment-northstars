// Secure · Microsoft: RequestHub hosted in Azure, plus an Azure Policy assignment that audits its storage account, in this
// solution's own resource group. Deploy from this folder with `azd up`; remove everything with `azd down --purge`.
targetScope = 'subscription'

@minLength(1)
@maxLength(24)
@description('azd environment name, for example ai-sdlc-secure. The resource group is rg-<name>.')
param environmentName string

@description('Region for the app, its database, and monitoring. PostgreSQL Flexible Server must be allowed there for your subscription.')
param location string

@description('Object id of the person running azd. Receives every RequestHub app role.')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@description('GitHub repository (owner/name) whose workflows scan, preview, and verify through OIDC. Set by the preprovision hook.')
param githubRepository string = ''

@description('OIDC subject prefix for repositories that use immutable subjects. Set by the preprovision hook.')
param githubOidcSubjectPrefix string = ''

var tags = {
  'azd-env-name': environmentName
  solution: '05-secure-microsoft'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

// Everything inside the resource group lives in resources.bicep, so a change can be previewed with a resource-group
// what-if (the infrastructure-remediation skill) by an identity that has no rights on the subscription.
module resources 'resources.bicep' = {
  name: 'resources'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    principalId: principalId
    principalType: principalType
    githubRepository: githubRepository
    githubOidcSubjectPrefix: githubOidcSubjectPrefix
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name
output GITHUB_ENVIRONMENT string = resources.outputs.githubEnvironment
output POLICY_ASSIGNMENT_NAME string = resources.outputs.policyAssignmentName
output STORAGE_ACCOUNT_NAME string = resources.outputs.storageAccountName

// Read by app/infra/api.parameters.json and worker.parameters.json when `azd deploy` ships the container apps.
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.registryLoginServer
output AZURE_CONTAINER_REGISTRY_NAME string = resources.outputs.registryName
output AZURE_CONTAINER_ENVIRONMENT_NAME string = resources.outputs.containerAppsEnvironmentName
output APP_IDENTITY_ID string = resources.outputs.appIdentityId
output APP_IDENTITY_CLIENT_ID string = resources.outputs.appIdentityClientId
output APP_IDENTITY_NAME string = resources.outputs.appIdentityName
output APPLICATIONINSIGHTS_CONNECTION_STRING string = resources.outputs.appInsightsConnectionString
output POSTGRES_HOST string = resources.outputs.postgresHost
output POSTGRES_DATABASE string = resources.outputs.postgresDatabase
output STORAGE_BLOB_ENDPOINT string = resources.outputs.storageBlobEndpoint
output API_APP_NAME string = resources.outputs.apiAppName
output WORKER_APP_NAME string = resources.outputs.workerAppName
output API_URL string = resources.outputs.apiUrl
output API_CLIENT_ID string = resources.outputs.apiClientId
output API_IDENTIFIER_URI string = resources.outputs.apiIdentifierUri
output AUTOMATION_CLIENT_ID string = resources.outputs.automationClientId
