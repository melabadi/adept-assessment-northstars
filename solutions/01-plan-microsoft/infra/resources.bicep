// Resources for the Plan · Microsoft solution (resource-group scope):
//   - Microsoft Foundry: the project, the chat model, and Application Insights for the agent's traces. The agent, its
//     vector store, the evaluators, and the evaluation are data-plane objects that the azd hook (setup_foundry.py)
//     publishes from agent.yaml and evaluators/.
//   - The run: an Azure Function app on the Flex Consumption plan (../function). Three functions: an HTTP start, a
//     storage queue for the long steps, and a timer that reads the review Issues. Each run's state is one blob.
//   - Network: tenant policy turns public network access off on storage and Key Vault, so the Function app reaches
//     its storage (runs, queue, code package) and Key Vault (the GitHub token) through private endpoints in its own
//     virtual network. No keys: storage disables shared keys, and the Function app signs in with its managed identity.
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
var storageBlobDataOwner = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var storageQueueDataContributor = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'
var projectEndpoint = 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'

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

// ---------- Network: the Function app reaches its storage and Key Vault through private endpoints ----------
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-plan'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.43.0.0/16'] }
    subnets: [
      {
        name: 'snet-function'
        properties: {
          addressPrefix: '10.43.0.0/26'
          delegations: [{ name: 'flex', properties: { serviceName: 'Microsoft.App/environments' } }]
        }
      }
      {
        name: 'snet-private-endpoints'
        properties: { addressPrefix: '10.43.1.0/27' }
      }
    ]
  }
}

// Blob: the run records and the code package. Queue: the run's steps. Vault: the GitHub token.
var privateLinks = [
  { name: 'blob', zone: 'privatelink.blob.${environment().suffixes.storage}' }
  { name: 'queue', zone: 'privatelink.queue.${environment().suffixes.storage}' }
  { name: 'vault', zone: 'privatelink.vaultcore.azure.net' }
]

resource privateZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for link in privateLinks: {
  name: link.zone
  location: 'global'
  tags: tags
}]

resource privateZoneLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (link, i) in privateLinks: {
  parent: privateZones[i]
  name: 'vnet-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}]

resource privateEndpoints 'Microsoft.Network/privateEndpoints@2024-05-01' = [for link in privateLinks: {
  name: 'pe-${link.name}-plan'
  location: location
  tags: tags
  properties: {
    subnet: { id: vnet.properties.subnets[1].id }
    privateLinkServiceConnections: [
      {
        name: link.name
        properties: {
          privateLinkServiceId: link.name == 'vault' ? vault.id : storage.id
          groupIds: [link.name]
        }
      }
    ]
  }
}]

resource privateDnsGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = [for (link, i) in privateLinks: {
  parent: privateEndpoints[i]
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{ name: link.name, properties: { privateDnsZoneId: privateZones[i].id } }]
  }
}]

// ---------- Storage: the run records, the steps queue, and the Function app's code package ----------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${resourceToken}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for name in ['function-package', 'runs']: {
  parent: blobService
  name: name
  properties: { publicAccess: 'None' }
}]

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource stepsQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queueService
  name: 'plan-steps'
}

// ---------- Key Vault: the GitHub token, readable only by the Function app ----------
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${resourceToken}'
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}

// Written through Azure Resource Manager from a secure parameter: deployment history never shows the value. Until
// PLAN_GITHUB_TOKEN is set there's no secret, and a run fails with GitHubTokenMissing when it opens the review Issue.
resource githubTokenSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(githubToken)) {
  parent: vault
  name: 'github-token'
  properties: {
    value: githubToken
    contentType: 'text/plain'
  }
}

// ---------- The Function app: start, steps, and the timer that reads the review Issues ----------
resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'asp-plan'
  location: location
  tags: tags
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: 'func-${resourceToken}'
  location: location
  tags: union(tags, { 'azd-service-name': 'function' })
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    virtualNetworkSubnetId: vnet.properties.subnets[0].id
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}function-package'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 40
        instanceMemoryMB: 2048
      }
      runtime: { name: 'python', version: '3.12' }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      appSettings: [
        // The host's storage (timer locks, queue, keys) through the private endpoints, with the managed identity.
        { name: 'AzureWebJobsStorage__blobServiceUri', value: storage.properties.primaryEndpoints.blob }
        { name: 'AzureWebJobsStorage__queueServiceUri', value: storage.properties.primaryEndpoints.queue }
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        // Application Insights accepts Microsoft Entra ID only (DisableLocalAuth): the Function app signs in to send logs.
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'APPLICATIONINSIGHTS_AUTHENTICATION_STRING', value: 'Authorization=AAD' }
        { name: 'FOUNDRY_PROJECT_ENDPOINT', value: projectEndpoint }
        { name: 'GITHUB_REPOSITORY', value: githubRepository }
        { name: 'KEY_VAULT_URI', value: vault.properties.vaultUri }
        { name: 'STORAGE_BLOB_ENDPOINT', value: storage.properties.primaryEndpoints.blob }
      ]
    }
  }
  dependsOn: [containers, stepsQueue, privateDnsGroups, privateZoneLinks]
}

// ---------- Who may use the agent and run evaluations: the presenter and the Function app ----------
resource presenterFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, principalId, foundryUser)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUser)
  }
}

resource functionFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, functionApp.id, foundryUser)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUser)
  }
}

// The Function app's storage: its code package, the host's locks and keys, and the run records (blob); its steps (queue).
resource functionBlobOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, functionApp.id, storageBlobDataOwner)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwner)
  }
}

resource functionQueueContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, functionApp.id, storageQueueDataContributor)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributor)
  }
}

// Reads the GitHub token; nothing else (and nobody else) reads Key Vault's secrets.
resource functionSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, functionApp.id, keyVaultSecretsUser)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUser)
  }
}

resource functionPublishesTelemetry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: appInsights
  name: guid(appInsights.id, functionApp.id, monitoringMetricsPublisher)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringMetricsPublisher)
  }
}

output foundryAccountName string = foundry.name
output foundryProjectName string = project.name
output foundryProjectEndpoint string = projectEndpoint
output foundryModelDeployment string = chatDeployment.name
output functionAppName string = functionApp.name
output appInsightsName string = appInsights.name