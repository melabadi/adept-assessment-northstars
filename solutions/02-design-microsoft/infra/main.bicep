// Design · Microsoft: the Azure resources for this solution, in its own resource group.
// Deploy from this folder with `azd up`. Remove everything with `azd down --purge`.
targetScope = 'subscription'

@minLength(1)
@maxLength(24)
@description('azd environment name, for example ai-sdlc-design. The resource group is rg-<name>.')
param environmentName string

@description('Region for the resource group and Microsoft Foundry. The model below must be available there, for example eastus2.')
param location string

@description('Region for Azure AI Search. Capacity varies by region; centralus has been reliable.')
param searchLocation string = 'centralus'

@description('Object id of the person running azd. Receives the roles the scripts need on Foundry and Azure AI Search.')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@description('GitHub repository (owner/name) whose workflows run the advisor through OIDC. Set by the preprovision hook.')
param githubRepository string = ''

@description('OIDC subject prefix for repositories that use immutable subjects. Set by the preprovision hook.')
param githubOidcSubjectPrefix string = ''

@description('Chat model for the architecture advisor agents. agent.yaml sets a reasoning effort, so pick a gpt-5 family model or switch agent.yaml to temperature.')
param modelName string = 'gpt-5.4-mini'
param modelVersion string = '2026-03-17'

@description('Model capacity in thousands of tokens per minute. The evaluation runs two cases at a time; 250 leaves room for both.')
param modelCapacity int = 250

var tags = {
  'azd-env-name': environmentName
  solution: '02-design-microsoft'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'design-microsoft'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    searchLocation: searchLocation
    principalId: principalId
    principalType: principalType
    githubRepository: githubRepository
    githubOidcSubjectPrefix: githubOidcSubjectPrefix
    githubEnvironment: 'design-microsoft'
    modelName: modelName
    modelVersion: modelVersion
    modelCapacity: modelCapacity
    tags: tags
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name
output FOUNDRY_ACCOUNT_NAME string = resources.outputs.foundryAccountName
output FOUNDRY_PROJECT_NAME string = resources.outputs.foundryProjectName
output FOUNDRY_PROJECT_ENDPOINT string = resources.outputs.foundryProjectEndpoint
output FOUNDRY_MODEL_DEPLOYMENT string = resources.outputs.foundryModelDeployment
output SEARCH_SERVICE_NAME string = resources.outputs.searchServiceName
output SEARCH_ENDPOINT string = resources.outputs.searchEndpoint
output SEARCH_CONNECTION_NAME string = resources.outputs.searchConnectionName
output AUTOMATION_CLIENT_ID string = resources.outputs.automationClientId
output GITHUB_ENVIRONMENT string = 'design-microsoft'
