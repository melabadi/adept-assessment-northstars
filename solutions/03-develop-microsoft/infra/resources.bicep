// The Azure pull request reviewer's resources, all in this solution's resource group:
// - monitoring, where Microsoft Foundry writes the agent's traces;
// - Microsoft Foundry: the account, the project, the model, and two project connections (tracing and the sandbox tool);
// - two Azure Container Apps session pools (Shell sessions): one to check the team's rules, one to build and test;
// - the Logic App that runs one review per pull request event;
// - least-privilege role assignments between them. No key or secret is created; the GitHub token is a securestring
//   Logic App parameter that the Azure Resource Manager API never returns.
param environmentName string
param location string
param aiLocation string
param principalId string
param principalType string
param githubRepository string
@secure()
param githubToken string
param checkerRef string
param reviewLabel string
param modelName string
param modelVersion string
param modelCapacity int
param reviewerAgentName string
param tags object

var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var roles = {
  foundryUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d' // Foundry User (formerly Azure AI User): run agents and evaluations
  sessionExecutor: '0fb8eba5-a2bb-4abe-b1c1-49dfad359bb0' // Azure ContainerApps Session Executor: run code in sessions
}
// Shell sessions (Ubuntu with bash, Python, Node, and apt) aren't in the Bicep type definitions yet; the API accepts them.
var shellSessions = any('Shell')

// ---------- Monitoring ----------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${resourceToken}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${resourceToken}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ---------- Sandbox: Azure Container Apps dynamic sessions ----------
// The judge pool reads the pull request as data and never runs its code; it has no network access. Its sessions live
// long enough to format the review at the end.
resource judgePool 'Microsoft.App/sessionPools@2026-07-01' = {
  name: 'judgepool'
  location: aiLocation
  tags: tags
  properties: {
    poolManagementType: 'Dynamic'
    containerType: shellSessions
    dynamicPoolConfiguration: {
      lifecycleConfiguration: { lifecycleType: 'Timed', cooldownPeriodInSeconds: 1800 }
    }
    scaleConfiguration: { maxConcurrentSessions: 10 }
    sessionNetworkConfiguration: { status: 'EgressDisabled' }
  }
}

// The run pool builds and tests the pull request's code. It needs the network to install the .NET SDK, Node.js,
// PostgreSQL, and packages. Nothing secret is ever placed in its sessions.
resource runPool 'Microsoft.App/sessionPools@2026-07-01' = {
  name: 'runpool'
  location: aiLocation
  tags: tags
  properties: {
    poolManagementType: 'Dynamic'
    containerType: shellSessions
    dynamicPoolConfiguration: {
      lifecycleConfiguration: { lifecycleType: 'Timed', cooldownPeriodInSeconds: 900 }
    }
    scaleConfiguration: { maxConcurrentSessions: 10 }
    sessionNetworkConfiguration: { status: 'EgressEnabled' }
  }
}

// ---------- Microsoft Foundry ----------
resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'aif-${resourceToken}'
  location: aiLocation
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
  location: aiLocation
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'AI-SDLC Develop'
    description: 'Pull request reviewer for the Develop phase (Microsoft track).'
  }
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: modelName
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
  }
  // Operations on one Foundry account must run one at a time.
  dependsOn: [project]
}

// Server-side tracing: once Application Insights is connected, Foundry traces every agent run with no code change.
resource tracing 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'appinsights'
  properties: {
    category: 'AppInsights'
    target: appInsights.id
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: { key: appInsights.properties.ConnectionString }
    metadata: { ApiType: 'Azure', ResourceId: appInsights.id }
  }
  dependsOn: [model]
}

// The agent's sandbox tool calls the run pool with the project's managed identity; the connection stores no secret.
resource sandboxConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'sandbox'
  properties: any({
    category: 'OpenAPI'
    authType: 'ProjectManagedIdentity'
    target: runPool.properties.poolManagementEndpoint
    audience: 'https://dynamicsessions.io'
    isSharedToAll: true
    metadata: { type: 'openapi' }
  })
  dependsOn: [tracing]
}

var projectEndpoint = 'https://${account.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'

// ---------- The reviewer: a Consumption Logic App ----------
resource reviewer 'Microsoft.Logic/workflows@2019-05-01' = {
  name: 'logic-pr-reviewer'
  location: aiLocation
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    state: 'Enabled'
    definition: loadJsonContent('reviewer-workflow.json')
    parameters: {
      repository: { value: githubRepository }
      githubToken: { value: githubToken }
      checkerRef: { value: checkerRef }
      reviewLabel: { value: reviewLabel }
      judgePool: { value: judgePool.properties.poolManagementEndpoint }
      runPool: { value: runPool.properties.poolManagementEndpoint }
      projectEndpoint: { value: projectEndpoint }
      agentName: { value: reviewerAgentName }
    }
  }
}

// ---------- Roles ----------
// The Logic App runs code in both pools and calls the agent.
resource reviewerJudge 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: judgePool
  name: guid(judgePool.id, reviewer.id, roles.sessionExecutor)
  properties: {
    principalId: reviewer.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.sessionExecutor)
  }
}

resource reviewerRun 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: runPool
  name: guid(runPool.id, reviewer.id, roles.sessionExecutor)
  properties: {
    principalId: reviewer.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.sessionExecutor)
  }
}

resource reviewerFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, reviewer.id, roles.foundryUser)
  properties: {
    principalId: reviewer.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}

// The agent's sandbox tool reads files in the run pool's session; it never gets the judge pool.
resource projectRun 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: runPool
  name: guid(runPool.id, project.id, roles.sessionExecutor)
  properties: {
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.sessionExecutor)
  }
}

// The presenter publishes and evaluates the agent and may open sessions to look around.
resource presenterFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, principalId, roles.foundryUser)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}

resource presenterJudge 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: judgePool
  name: guid(judgePool.id, principalId, roles.sessionExecutor)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.sessionExecutor)
  }
}

resource presenterRun 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: runPool
  name: guid(runPool.id, principalId, roles.sessionExecutor)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.sessionExecutor)
  }
}

output foundryAccountName string = account.name
output projectEndpoint string = projectEndpoint
output modelDeployment string = model.name
output logicAppName string = reviewer.name
output judgePoolEndpoint string = judgePool.properties.poolManagementEndpoint
output runPoolEndpoint string = runPool.properties.poolManagementEndpoint
output sandboxConnectionId string = sandboxConnection.id
output appInsightsName string = appInsights.name
