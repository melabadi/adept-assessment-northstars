// Resources for the Design · Microsoft solution (resource-group scope): a Microsoft Foundry project with a chat model,
// Azure AI Search for the approved architecture standards, the connection between them, and the identity GitHub
// Actions uses through OIDC. No keys anywhere: Foundry and Search both have local (key) authentication disabled.
param environmentName string
param location string
param searchLocation string
param principalId string
param principalType string
param githubRepository string
param githubOidcSubjectPrefix string
param githubEnvironment string
param modelName string
param modelVersion string
param modelCapacity int
param resourceSeed string
param tags object

var resourceToken = toLower(empty(resourceSeed)
  ? uniqueString(subscription().id, resourceGroup().id, environmentName)
  : uniqueString(subscription().id, resourceGroup().id, environmentName, resourceSeed))
// GitHub OIDC tokens use either the classic subject (repo:owner/name) or the immutable one (repo:owner@id/name@id).
var githubSubjectPrefix = empty(githubOidcSubjectPrefix) ? 'repo:${githubRepository}' : githubOidcSubjectPrefix
var roles = {
  // Foundry User (formerly Azure AI User): create agent versions and call agents.
  foundryUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchIndexDataReader: '1407120a-92aa-4202-b7e9-c0e197c71c8f'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
}

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
  name: 'design'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'AI-SDLC Design'
    description: 'Architecture advisor agents grounded in the approved standards (Design phase, Microsoft track).'
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

// ---------- Azure AI Search: the approved architecture standards ----------
resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: 'srch-${resourceToken}'
  location: searchLocation
  tags: tags
  sku: { name: 'basic' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    // The standard plan keeps semantic ranking working after the free monthly allowance (pay per request beyond it).
    semanticSearch: 'standard'
    disableLocalAuth: true
    publicNetworkAccess: 'enabled'
  }
}

// The agents' Azure AI Search tool reaches the index through this project connection, with Microsoft Entra ID.
resource searchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'standards-search'
  properties: {
    category: 'CognitiveSearch'
    target: 'https://${search.name}.search.windows.net'
    authType: 'AAD'
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      ResourceId: search.id
    }
  }
  dependsOn: [chatDeployment]
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

// ---------- Who may do what ----------
// The presenter and the GitHub workflows publish agents, call them, and keep the standards index in sync.
// Loop keys are static; principal ids resolve at deploy time.
var operators = ['presenter', 'automation']

resource operatorFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for key in operators: {
  scope: foundry
  name: guid(foundry.id, key == 'presenter' ? principalId : automationIdentity.id, roles.foundryUser)
  properties: {
    principalId: key == 'presenter' ? principalId : automationIdentity.properties.principalId
    principalType: key == 'presenter' ? principalType : 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}]

resource operatorSearchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for key in operators: {
  scope: search
  name: guid(search.id, key == 'presenter' ? principalId : automationIdentity.id, roles.searchIndexDataContributor)
  properties: {
    principalId: key == 'presenter' ? principalId : automationIdentity.properties.principalId
    principalType: key == 'presenter' ? principalType : 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor)
  }
}]

resource operatorSearchService 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for key in operators: {
  scope: search
  name: guid(search.id, key == 'presenter' ? principalId : automationIdentity.id, roles.searchServiceContributor)
  properties: {
    principalId: key == 'presenter' ? principalId : automationIdentity.properties.principalId
    principalType: key == 'presenter' ? principalType : 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchServiceContributor)
  }
}]

// The agents' search tool runs as Foundry: it only reads the index. Current docs name the account's identity and
// earlier ones the project's, so both get the same read access.
var foundryIdentities = ['account', 'project']

resource foundrySearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for key in foundryIdentities: {
  scope: search
  name: guid(search.id, key == 'account' ? foundry.id : project.id, roles.searchIndexDataReader)
  properties: {
    principalId: key == 'account' ? foundry.identity.principalId : project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataReader)
  }
}]

resource foundrySearchService 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for key in foundryIdentities: {
  scope: search
  name: guid(search.id, key == 'account' ? foundry.id : project.id, roles.searchServiceContributor)
  properties: {
    principalId: key == 'account' ? foundry.identity.principalId : project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchServiceContributor)
  }
}]

output foundryAccountName string = foundry.name
output foundryProjectName string = project.name
output foundryProjectEndpoint string = 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
output foundryModelDeployment string = chatDeployment.name
output searchServiceName string = search.name
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output searchConnectionName string = searchConnection.name
output automationClientId string = automationIdentity.properties.clientId
