// Test · Microsoft: RequestHub hosted in Azure plus an Azure Load Testing resource that runs an authenticated load test
// against it, in this solution's own resource group. Deploy from this folder with `azd up`; remove everything with
// `azd down --purge`.
targetScope = 'subscription'

@minLength(1)
@maxLength(24)
@description('azd environment name, for example ai-sdlc-test. The resource group is rg-<name>.')
param environmentName string

@description('Region for the app, its database, monitoring, and the load test engines. PostgreSQL Flexible Server must be allowed there for your subscription.')
param location string

@description('Object id of the person running azd. Receives every RequestHub app role and may create and run load tests.')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@description('GitHub repository (owner/name) whose workflows run the load test through OIDC. Set by the preprovision hook.')
param githubRepository string = ''

@description('OIDC subject prefix for repositories that use immutable subjects. Set by the preprovision hook.')
param githubOidcSubjectPrefix string = ''

var githubEnvironment = 'test-microsoft'
var tags = {
  'azd-env-name': environmentName
  solution: '04-test-microsoft'
}
// Extra roles for the GitHub Actions identity on this resource group: Container Apps Contributor lets the workflow inject
// and remove the rehearsal slowdown; Monitoring Reader lets the report read Application Insights.
var automationRoles = [
  '358470bc-b998-42bd-ab17-a7e34c199c0f'
  '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
]

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
    automationRoleDefinitionIds: automationRoles
    // The workflow runs and reports load tests; it never builds images, and only calls the API as a requester.
    automationCanPushImages: false
    automationAppRoleNames: ['Requester']
    tags: tags
  }
}

// Created first, in parallel with the app platform, so Microsoft Graph knows the identities before loadtesting.bicep
// assigns their RequestHub app roles.
module loadTestIdentities 'loadtest-identities.bicep' = {
  name: 'loadtest-identities'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    tags: tags
  }
}

module loadTesting 'loadtesting.bicep' = {
  name: 'loadtesting'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    principalId: principalId
    principalType: principalType
    automationPrincipalId: app.outputs.automationPrincipalId
    apiClientId: app.outputs.apiClientId
    requesterIdentityName: loadTestIdentities.outputs.requesterName
    approverIdentityName: loadTestIdentities.outputs.approverName
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
// The API accepts tokens from the two load-test identities, and lets the requester identity clean up its own requests.
output LOAD_TEST_CLIENT_IDS string = '${loadTestIdentities.outputs.requesterClientId},${loadTestIdentities.outputs.approverClientId}'
output LOAD_TEST_REQUESTER_IDS string = 'aad-${loadTestIdentities.outputs.requesterPrincipalId}'

// Read by load_test.py and slowdown.py (and published to the GitHub environment by configure_github.py).
output APPLICATIONINSIGHTS_NAME string = app.outputs.appInsightsName
output LOAD_TEST_NAME string = loadTesting.outputs.loadTestName
output LOAD_TEST_REQUESTER_IDENTITY string = loadTestIdentities.outputs.requesterName
output LOAD_TEST_APPROVER_IDENTITY string = loadTestIdentities.outputs.approverName
