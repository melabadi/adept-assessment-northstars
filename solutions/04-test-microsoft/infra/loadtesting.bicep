// Azure Load Testing for the Test · Microsoft solution, deployed into the resource group that hosts RequestHub.
//
// The load test signs in to RequestHub with two dedicated managed identities (loadtest-identities.bicep), never with a
// person's account or a secret:
//   - the requester identity (RequestHub Requester app role) submits synthetic requests and may delete its own requests;
//   - the approver identity (RequestHub Approver app role) decides some of them, so nobody decides their own request.
// Both identities are assigned to the Load Testing resource, which lends them to the test engines during a run. The
// presenter may create and run tests (Load Test Contributor). The resource's own identity reads the app's metrics
// (Monitoring Reader) so the test dashboard shows server-side metrics next to the client results.
extension microsoftGraphV1

param environmentName string
param location string

@description('Object id of the presenter, who creates and runs tests.')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@description('Client id of RequestHub\'s Microsoft Entra app registration, whose app roles the load-test identities receive.')
param apiClientId string

@description('Names of the two identities created by loadtest-identities.bicep.')
param requesterIdentityName string
param approverIdentityName string

param tags object = {}

// Same token as app/infra/requesthub.bicep, so every resource in the group shares one suffix.
var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var roles = {
  loadTestContributor: '749a398d-560b-491b-bb21-08924219302e'
  monitoringReader: '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
}

resource requester 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: requesterIdentityName
}

resource approver 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: approverIdentityName
}

resource loadTest 'Microsoft.LoadTestService/loadTests@2022-12-01' = {
  name: 'lt-${resourceToken}'
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned,UserAssigned'
    userAssignedIdentities: {
      '${requester.id}': {}
      '${approver.id}': {}
    }
  }
  properties: {
    description: 'RequestHub performance lab: authenticated request-and-approval journey with pass/fail criteria.'
  }
}

resource tester 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: loadTest
  name: guid(loadTest.id, principalId, roles.loadTestContributor)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.loadTestContributor)
  }
}

resource metricsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, loadTest.id, roles.monitoringReader)
  properties: {
    principalId: loadTest.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.monitoringReader)
  }
}

// RequestHub app roles, assigned to the identities as applications. The API maps them to RequestHub roles.
resource apiServicePrincipal 'Microsoft.Graph/servicePrincipals@v1.0' existing = {
  appId: apiClientId
}

resource requesterAppRole 'Microsoft.Graph/appRoleAssignedTo@v1.0' = {
  appRoleId: filter(apiServicePrincipal.appRoles, role => role.value == 'RequestHub.Requester')[0].id
  principalId: requester.properties.principalId
  resourceId: apiServicePrincipal.id
}

resource approverAppRole 'Microsoft.Graph/appRoleAssignedTo@v1.0' = {
  appRoleId: filter(apiServicePrincipal.appRoles, role => role.value == 'RequestHub.Approver')[0].id
  principalId: approver.properties.principalId
  resourceId: apiServicePrincipal.id
}

output loadTestName string = loadTest.name
