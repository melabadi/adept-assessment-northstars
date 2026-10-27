// The two managed identities the load test signs in to RequestHub with. They live in their own module so they are created
// at the start of the deployment, minutes before their RequestHub app roles are assigned in loadtesting.bicep: Microsoft
// Graph rejects an app role assignment for an identity it has not replicated yet.
param environmentName string
param location string
param tags object = {}

// Same token as app/infra/requesthub.bicep, so every resource in the group shares one suffix.
var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))

@description('Submits synthetic requests (RequestHub Requester) and may delete the requests it submitted.')
resource requester 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-lt-requester-${resourceToken}'
  location: location
  tags: tags
}

@description('Decides some of those requests (RequestHub Approver), so nobody decides their own request.')
resource approver 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-lt-approver-${resourceToken}'
  location: location
  tags: tags
}

output requesterName string = requester.name
output requesterClientId string = requester.properties.clientId
output requesterPrincipalId string = requester.properties.principalId
output approverName string = approver.name
output approverClientId string = approver.properties.clientId
