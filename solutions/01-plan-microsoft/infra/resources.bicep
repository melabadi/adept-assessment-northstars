// Resources for the Plan · Microsoft solution (resource-group scope): a Microsoft Foundry project with a chat model
// and agent tracing, and the Logic App that runs the agent, scores its brief, and waits for a person.
param environmentName string
param location string
param principalId string
param principalType string
param githubRepository string
@secure()
param githubToken string
param modelName string
param modelVersion string
param modelCapacity int
param tags object

var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
// Foundry User (formerly Azure AI User): run agents and evaluations, and use the project's data plane.
var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var monitoringMetricsPublisher = '3913510d-42f4-4e42-8a64-420c390055eb'
var logAnalyticsReader = '73c42c96-874c-492b-b04d-ab87d138a893'

// The agent's name and the request the Logic App sends it come from agent.yaml, the agent's versioned definition.
var agent = loadYamlContent('../agent.yaml')

// Quotes for the published Issues: each transcript paragraph and policy, read from inputs/ when the template compiles.
func excerpt(text string) string => length(text) > 220 ? '${substring(text, 0, 217)}...' : text
var transcriptLines = split(replace(loadTextContent('../inputs/stakeholder-transcript.md'), '\r', ''), '\n')
var paragraphLines = filter(transcriptLines, line => startsWith(line, '**[T'))
var policyRows = filter(split(replace(loadTextContent('../inputs/routing-policies.md'), '\r', ''), '\n'), line => startsWith(line, '| POL-'))
var sourceExcerpts = union(
  toObject(paragraphLines, line => substring(line, 3, 3), line => excerpt(trim(substring(line, 9)))),
  toObject(policyRows, row => trim(split(row, '|')[1]), row => excerpt('Policy "${trim(split(row, '|')[3])}" v${trim(split(row, '|')[2])}: ${trim(split(row, '|')[4])}'))
)

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

// ---------- Agent tracing: Application Insights connected to the project, Microsoft Entra ID only ----------
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-plan'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-plan'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
    DisableLocalAuth: true
  }
}

// Server-side tracing: Foundry sends the agent's traces with the project's managed identity.
resource tracing 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'appi-plan'
  properties: {
    category: 'AppInsights'
    target: appInsights.id
    // The service accepts ProjectManagedIdentity or ApiKey here; the published Bicep types don't list the first yet.
    #disable-next-line BCP036
    authType: 'ProjectManagedIdentity'
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      ResourceId: appInsights.id
      // Where to send traces. Local authentication is disabled, so sending also needs the project's Entra token.
      ApplicationInsightsConnectionString: appInsights.properties.ConnectionString
    }
  }
  dependsOn: [chatDeployment]
}

resource projectPublishesTraces 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: appInsights
  name: guid(appInsights.id, project.id, monitoringMetricsPublisher)
  properties: {
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringMetricsPublisher)
  }
}

resource presenterReadsTraces 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: appInsights
  name: guid(appInsights.id, principalId, logAnalyticsReader)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', logAnalyticsReader)
  }
}

// ---------- The workflow: run the agent, score the brief, wait for a person, publish ----------
resource workflow 'Microsoft.Logic/workflows@2019-05-01' = {
  name: 'logic-plan-backlog'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    state: 'Enabled'
    definition: loadJsonContent('workflow.json')
    parameters: {
      foundryProjectEndpoint: { value: 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}' }
      agentName: { value: agent.name }
      agentPrompt: { value: agent.prompt }
      evaluationName: { value: 'plan-brief-checks' }
      githubRepository: { value: githubRepository }
      // A securestring workflow parameter: reading the workflow never returns it, and every action that uses it
      // hides its inputs and outputs in the run history.
      githubToken: { value: githubToken }
      sourceExcerpts: { value: sourceExcerpts }
    }
  }
}

// ---------- Who may use the agent and run evaluations: the presenter and the workflow ----------
resource presenterFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, principalId, foundryUser)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUser)
  }
}

resource workflowFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, workflow.id, foundryUser)
  properties: {
    principalId: workflow.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUser)
  }
}

output foundryAccountName string = foundry.name
output foundryProjectName string = project.name
output foundryProjectEndpoint string = 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
output foundryModelDeployment string = chatDeployment.name
output logicAppName string = workflow.name
output appInsightsName string = appInsights.name
