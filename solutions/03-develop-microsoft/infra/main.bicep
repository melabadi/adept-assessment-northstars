// Develop · Microsoft: an Azure-hosted pull request reviewer, in this solution's own resource group.
// A GitHub webhook calls a Python Azure Function, which queues the review and runs it: it checks the pull request against
// the team's rules in one Azure Container Apps sandbox session, builds and tests it in another, asks a Microsoft Foundry
// agent for commentary, and posts one COMMENT review. Deploy from this folder with `azd up`; remove everything with
// `azd down --purge`.
targetScope = 'subscription'

@minLength(1)
@maxLength(24)
@description('azd environment name, for example ai-sdlc-develop. The resource group is rg-<name>.')
param environmentName string

@description('Region for the resource group and monitoring.')
param location string

@description('Region for Microsoft Foundry, the sandbox session pools, and the Function with its storage and network. The model below must be available there.')
param aiLocation string = 'eastus2'

@description('Object id of the person running azd. Receives the Foundry User role and may run sandbox sessions.')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@minLength(3)
@description('GitHub repository (owner/name) whose pull requests are reviewed. Set it with `azd env set GITHUB_REPOSITORY`.')
param githubRepository string

@secure()
@description('Fine-grained GitHub token for that repository only: Contents read, Pull requests read and write. Empty until you set GITHUB_REVIEW_TOKEN. Stored only in Key Vault.')
param githubToken string = ''

@secure()
@description('Secret GitHub signs every webhook delivery with. The preprovision hook generates it once (GITHUB_WEBHOOK_SECRET). Stored only in Key Vault.')
param githubWebhookSecret string = ''

@description('Git ref the rule checker, the sandbox runner, and the review formatter are read from. Never the pull request itself.')
param checkerRef string = 'main'

@description('Label that asks for a review.')
param reviewLabel string = 'review:azure'

@description('Reasoning model for the reviewer agent.')
param modelName string = 'gpt-5.4-mini'
param modelVersion string = '2026-03-17'

@description('Model capacity in thousands of tokens per minute.')
param modelCapacity int = 150

@description('Name of the Foundry agent the Function calls. publish_reviewer_agent.py publishes it after each provision.')
param reviewerAgentName string = 'requesthub-pr-reviewer'

var tags = {
  'azd-env-name': environmentName
  solution: '03-develop-microsoft'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module reviewer 'resources.bicep' = {
  name: 'pr-reviewer'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    aiLocation: aiLocation
    principalId: principalId
    principalType: principalType
    githubRepository: githubRepository
    githubToken: githubToken
    githubWebhookSecret: githubWebhookSecret
    checkerRef: checkerRef
    reviewLabel: reviewLabel
    modelName: modelName
    modelVersion: modelVersion
    modelCapacity: modelCapacity
    reviewerAgentName: reviewerAgentName
    tags: tags
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name
output GITHUB_REPOSITORY string = githubRepository
output REVIEW_LABEL string = reviewLabel

output FOUNDRY_ACCOUNT_NAME string = reviewer.outputs.foundryAccountName
output FOUNDRY_PROJECT_ENDPOINT string = reviewer.outputs.projectEndpoint
output FOUNDRY_MODEL_DEPLOYMENT string = reviewer.outputs.modelDeployment
output REVIEWER_AGENT_NAME string = reviewerAgentName
output REVIEWER_FUNCTION_APP string = reviewer.outputs.functionAppName
output REVIEWER_FUNCTION_HOST string = reviewer.outputs.functionHostName
output KEY_VAULT_NAME string = reviewer.outputs.keyVaultName
output JUDGE_POOL_ENDPOINT string = reviewer.outputs.judgePoolEndpoint
output RUN_POOL_ENDPOINT string = reviewer.outputs.runPoolEndpoint
output SANDBOX_CONNECTION_ID string = reviewer.outputs.sandboxConnectionId
output APPLICATIONINSIGHTS_NAME string = reviewer.outputs.appInsightsName
