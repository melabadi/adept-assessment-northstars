// Design · Microsoft: the Azure resources for this solution, in its own resource group.
// Deploy from this folder with `azd up`. Remove everything with `azd down --purge`.
targetScope = 'subscription'

@minLength(1)
@maxLength(24)
@description('azd environment name, for example ai-sdlc-design. The resource group is rg-<name>.')
param environmentName string

@description('Region for the resource group, Microsoft Foundry, the Function, and the Logic Apps. The model below must be available there, for example eastus2.')
param location string

@description('Region for Azure AI Search. Capacity varies by region; centralus has been reliable.')
param searchLocation string = 'centralus'

@description('Object id of the person running azd. Receives the roles setup_azure.py needs on Foundry and Azure AI Search, and read access to the agents\' traces.')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@description('GitHub repository (owner/name) the advisor answers and writes ADR drafts to. Set by the preprovision hook.')
param githubRepository string

@description('Name proposed for the GitHub App on GitHub\'s registration page (the person creating it can change it).')
param githubAppName string = 'AI-SDLC design advisor'

@description('Chat model for the architecture advisor agents. agent.yaml sets a reasoning effort, so pick a gpt-5 family model or switch agent.yaml to temperature.')
param modelName string = 'gpt-5.4-mini'
param modelVersion string = '2026-03-17'

@description('Model capacity in thousands of tokens per minute. An evaluation run sends five cases at once per profile; 250 leaves room for two runs and the advisor.')
param modelCapacity int = 250

@description('Optional. Any new value gives every resource in the group a new name. Use it to re-create the solution right after azd down --purge, while the old Foundry name can still point to the deleted account.')
param resourceSeed string = ''

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
    githubAppName: githubAppName
    modelName: modelName
    modelVersion: modelVersion
    modelCapacity: modelCapacity
    resourceSeed: resourceSeed
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
output FUNCTION_APP_NAME string = resources.outputs.functionAppName
output KEY_VAULT_NAME string = resources.outputs.keyVaultName
output ADVISOR_WORKFLOW_NAME string = resources.outputs.advisorWorkflowName
output STANDARDS_WORKFLOW_NAME string = resources.outputs.standardsWorkflowName
output APPLICATIONINSIGHTS_NAME string = resources.outputs.appInsightsName
