// Microsoft Foundry for the Develop · Microsoft solution: an account and project with one chat model, and the Foundry User
// role for everyone who calls the triage agent (the presenter, the app's managed identity, and the GitHub Actions identity).
param environmentName string
param location string
param modelName string
param modelVersion string
param modelCapacity int

@description('Principals that may run the agent: [{ principalId, principalType }].')
param users array

param tags object

var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
// Foundry User (formerly Azure AI User): run agents and use the project's data plane.
var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'aif-${resourceToken}'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: 'aif-${resourceToken}'
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: 'develop'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'AI-SDLC Develop'
    description: 'RequestHub triage agent for the Develop phase (Microsoft track).'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: modelName
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
  }
  // Operations on one Foundry account must run one at a time.
  dependsOn: [project]
}

resource foundryUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for user in users: {
  scope: account
  name: guid(account.id, user.principalId, foundryUser)
  properties: {
    principalId: user.principalId
    principalType: user.principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUser)
  }
}]

output accountName string = account.name
output projectEndpoint string = 'https://${account.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
output modelDeployment string = chatDeployment.name
