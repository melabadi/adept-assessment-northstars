// Resources for the Plan · Microsoft solution (resource-group scope): a Microsoft Foundry project with a chat model,
// and the identity GitHub Actions uses to run the agent through OIDC.
param environmentName string
param location string
param principalId string
param principalType string
param githubRepository string
param githubOidcSubjectPrefix string
param githubEnvironment string
param modelName string
param modelVersion string
param modelCapacity int
param tags object

var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
// Foundry User (formerly Azure AI User): run agents and use the project's data plane.
var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
// GitHub OIDC tokens use either the classic subject (repo:owner/name) or the immutable one (repo:owner@id/name@id).
var githubSubjectPrefix = empty(githubOidcSubjectPrefix) ? 'repo:${githubRepository}' : githubOidcSubjectPrefix

// ---------- Microsoft Foundry ----------
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
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
  parent: foundry
  name: 'plan'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'AI-SDLC Plan'
    description: 'Requirements analyst agent for the Plan phase (Microsoft track).'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: modelName
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
  }
  // Operations on one Foundry account must run one at a time.
  dependsOn: [project]
}

// ---------- GitHub Actions identity (OIDC, no stored secrets) ----------
resource automationIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-github-${resourceToken}'
  location: location
  tags: tags
}

resource githubCredential 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (!empty(githubRepository)) {
  parent: automationIdentity
  // Azure rejects reserved words such as "microsoft" in resource names, so the GitHub environment name stays in the subject.
  name: 'github-oidc-environment'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: '${githubSubjectPrefix}:environment:${githubEnvironment}'
    audiences: ['api://AzureADTokenExchange']
  }
}

// ---------- Who may use the agent: the presenter and the GitHub workflow ----------
resource presenterFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, principalId, foundryUser)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUser)
  }
}

resource automationFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, automationIdentity.id, foundryUser)
  properties: {
    principalId: automationIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUser)
  }
}

output foundryAccountName string = foundry.name
output foundryProjectName string = project.name
output foundryProjectEndpoint string = 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
output foundryModelDeployment string = chatDeployment.name
output automationClientId string = automationIdentity.properties.clientId
