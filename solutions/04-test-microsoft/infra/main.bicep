// Test · Microsoft: RequestHub hosted in Azure, an Azure Load Testing resource that runs an authenticated load test
// against it, and a Logic App that reports every finished run to GitHub, in this solution's own resource group. Deploy
// from this folder with `azd up`; remove everything with `azd down --purge`. No GitHub workflow is involved: the
// postprovision hook (sync_test.py) copies the committed test into Azure Load Testing.
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

@description('GitHub repository (owner/name) where the Logic App opens Issues for failing runs. Set by the preprovision hook.')
param githubRepository string = ''

@secure()
@description('Fine-grained GitHub token for that repository only, with Issues read and write. Empty: reports are built but not posted.')
param githubIssuesToken string = ''

var tags = {
  'azd-env-name': environmentName
  solution: '04-test-microsoft'
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
    // No GitHub workflow in this solution: the automation identity gets no federated credential, roles, or app roles.
    automationCanPushImages: false
    automationAppRoleNames: []
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
    apiClientId: app.outputs.apiClientId
    requesterIdentityName: loadTestIdentities.outputs.requesterName
    approverIdentityName: loadTestIdentities.outputs.approverName
    tags: tags
  }
}

module reporting 'reporting.bicep' = {
  name: 'reporting'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    tags: tags
    loadTestName: loadTesting.outputs.loadTestName
    testId: 'requesthub-journey'
    logAnalyticsName: app.outputs.logAnalyticsName
    githubRepository: githubRepository
    githubToken: githubIssuesToken
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
// No workflow calls the API in this solution, so the API accepts no automation identity.
output AUTOMATION_CLIENT_ID string = ''
// The API accepts tokens from the two load-test identities, and lets the requester identity clean up its own requests.
output LOAD_TEST_CLIENT_IDS string = '${loadTestIdentities.outputs.requesterClientId},${loadTestIdentities.outputs.approverClientId}'
output LOAD_TEST_REQUESTER_IDS string = 'aad-${loadTestIdentities.outputs.requesterPrincipalId}'

// Read by sync_test.py and slowdown.py.
output APPLICATIONINSIGHTS_NAME string = app.outputs.appInsightsName
output LOAD_TEST_NAME string = loadTesting.outputs.loadTestName
output LOAD_TEST_REQUESTER_IDENTITY string = loadTestIdentities.outputs.requesterName
output LOAD_TEST_APPROVER_IDENTITY string = loadTestIdentities.outputs.approverName
output ACTION_GROUP_ID string = reporting.outputs.actionGroupId
output LOGIC_APP_NAME string = reporting.outputs.logicAppName
