// Plan · Microsoft: the Azure resources for this solution, in its own resource group.
// Deploy from this folder with `azd up`. Remove everything with `azd down --purge`.
targetScope = 'subscription'

@minLength(1)
@maxLength(24)
@description('azd environment name, for example ai-sdlc-plan. The resource group is rg-<name>.')
param environmentName string

@description('Region for the resource group and Microsoft Foundry. The model below must be available there, for example eastus2.')
param location string

@description('Object id of the person running azd. Receives the Foundry User role and read access to the agent traces.')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@description('GitHub repository (owner/name) where the Logic App creates the review Issue and the backlog. Set by the preprovision hook.')
param githubRepository string = ''

@secure()
@description('Fine-grained GitHub token for this repository only, with Issues read and write. Empty until you set GITHUB_TOKEN (README, Set up).')
param githubToken string = ''

@description('Chat model for the requirements analyst agent. agent.yaml sets temperature, so pick a non-reasoning model or switch agent.yaml to reasoning_effort.')
param modelName string = 'gpt-4.1'
param modelVersion string = '2025-04-14'

@description('Model capacity in thousands of tokens per minute.')
param modelCapacity int = 50

var tags = {
  'azd-env-name': environmentName
  solution: '01-plan-microsoft'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'plan-microsoft'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    principalId: principalId
    principalType: principalType
    githubRepository: githubRepository
    githubToken: githubToken
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
output LOGIC_APP_NAME string = resources.outputs.logicAppName
output APPLICATIONINSIGHTS_NAME string = resources.outputs.appInsightsName
