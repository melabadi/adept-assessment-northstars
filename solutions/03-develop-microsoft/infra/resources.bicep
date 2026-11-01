// The Azure pull request reviewer's resources, all in this solution's resource group:
// - monitoring: Application Insights for the agent's traces and the Function's logs;
// - Microsoft Foundry: the account, the project, the model, and two project connections (tracing and the sandbox tool);
// - two Azure Container Apps session pools (Shell sessions): one to check the team's rules, one to build and test;
// - the reviewer: a Python Azure Function on the Flex Consumption plan. GitHub's webhook calls it; it queues the review
//   and runs it from the queue. Its storage has no public network access and no shared keys (tenant policy), so the
//   Function reaches it through private endpoints in the solution's virtual network;
// - Key Vault, also closed to the internet and reached through a private endpoint: the GitHub token and the webhook
//   secret. Bicep writes them from secure parameters through Azure Resource Manager; they are never app settings, and
//   only the Function's identity can read them;
// - least-privilege role assignments between them. No key is created.
param environmentName string
param location string
param aiLocation string
param principalId string
param principalType string
param githubRepository string
@secure()
param githubToken string
@secure()
param githubWebhookSecret string
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
  storageBlobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b' // the Function's host, code package, and dry-run results
  storageQueueDataContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88' // the review queue
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6' // read the GitHub token and the webhook secret
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
// The judge pool reads the pull request as data and never runs its code; it has no network access. Its session waits,
// idle, while the change is built and the agent works (up to about 42 minutes in the worst case), then writes the review,
// so it gets the longest idle timeout sessions allow.
resource judgePool 'Microsoft.App/sessionPools@2026-07-01' = {
  name: 'judgepool'
  location: aiLocation
  tags: tags
  properties: {
    poolManagementType: 'Dynamic'
    containerType: shellSessions
    dynamicPoolConfiguration: {
      lifecycleConfiguration: { lifecycleType: 'Timed', cooldownPeriodInSeconds: 3600 }
    }
    scaleConfiguration: { maxConcurrentSessions: 10 }
    sessionNetworkConfiguration: { status: 'EgressDisabled' }
  }
}

// The run pool builds and tests the pull request's code. It needs the network to install the .NET SDK, Node.js,
// PostgreSQL, and packages. Nothing secret is ever placed in its sessions. A session stays up for 30 idle minutes, so
// the agent can still read it after a slow first attempt.
resource runPool 'Microsoft.App/sessionPools@2026-07-01' = {
  name: 'runpool'
  location: aiLocation
  tags: tags
  properties: {
    poolManagementType: 'Dynamic'
    containerType: shellSessions
    dynamicPoolConfiguration: {
      lifecycleConfiguration: { lifecycleType: 'Timed', cooldownPeriodInSeconds: 1800 }
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

// ---------- Network: the Function reaches its storage and Key Vault through private endpoints ----------
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-${resourceToken}'
  location: aiLocation
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

// Blob holds the Function's code package, its host files, and the dry-run results; queue holds the reviews to run;
// the vault holds the GitHub token and the webhook secret.
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
  name: 'pe-${link.name}-${resourceToken}'
  location: aiLocation
  tags: tags
  properties: {
    subnet: { id: vnet.properties.subnets[1].id }
    privateLinkServiceConnections: [
      {
        name: link.name
        properties: { privateLinkServiceId: link.name == 'vault' ? vault.id : storage.id, groupIds: [link.name] }
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

// ---------- Storage: the Function's code package and host files, the review queue, and dry-run results ----------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${resourceToken}'
  location: aiLocation
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

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for name in ['function-package', 'dry-runs']: {
  parent: blobService
  name: name
  properties: { publicAccess: 'None' }
}]

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource reviewQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queueService
  name: 'reviews'
}

// A dry run's result (the evaluation reads it within minutes) holds the pull request's review: keep it a week.
resource dryRunRetention 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'delete-dry-run-results'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: { blobTypes: ['blockBlob'], prefixMatch: ['dry-runs/'] }
            actions: { baseBlob: { delete: { daysAfterModificationGreaterThan: 7 } } }
          }
        }
      ]
    }
  }
}

// ---------- Key Vault: the GitHub token and the webhook secret ----------
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${resourceToken}'
  location: aiLocation
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

// Written through Azure Resource Manager, so this works although the vault takes no traffic from the internet. An empty
// parameter writes nothing: until the token is set, the Function says it has none.
resource githubTokenSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(githubToken)) {
  parent: vault
  name: 'github-review-token'
  properties: { value: githubToken, contentType: 'text/plain' }
}

resource webhookSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(githubWebhookSecret)) {
  parent: vault
  name: 'github-webhook-secret'
  properties: { value: githubWebhookSecret, contentType: 'text/plain' }
}

// ---------- The reviewer: a Python Azure Function on the Flex Consumption plan ----------
resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'plan-${resourceToken}'
  location: aiLocation
  tags: tags
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

resource reviewer 'Microsoft.Web/sites@2024-04-01' = {
  name: 'func-${resourceToken}'
  location: aiLocation
  tags: union(tags, { 'azd-service-name': 'reviewer' })
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
      // A review waits on the sandbox and the agent, so one instance runs several; ten instances is far more than a
      // repository needs, and keeps the bill bounded.
      scaleAndConcurrency: {
        maximumInstanceCount: 10
        instanceMemoryMB: 2048
      }
      runtime: { name: 'python', version: '3.12' }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'AzureWebJobsStorage__blobServiceUri', value: storage.properties.primaryEndpoints.blob }
        { name: 'AzureWebJobsStorage__queueServiceUri', value: storage.properties.primaryEndpoints.queue }
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'GITHUB_REPOSITORY', value: githubRepository }
        { name: 'KEY_VAULT_URI', value: vault.properties.vaultUri }
        { name: 'REVIEW_LABEL', value: reviewLabel }
        { name: 'REVIEW_CHECKER_REF', value: checkerRef }
        { name: 'REVIEW_SCRIPTS_PATH', value: 'solutions/03-develop-microsoft/sandbox' }
        { name: 'REVIEWER_AGENT_NAME', value: reviewerAgentName }
        { name: 'JUDGE_POOL_ENDPOINT', value: judgePool.properties.poolManagementEndpoint }
        { name: 'RUN_POOL_ENDPOINT', value: runPool.properties.poolManagementEndpoint }
        { name: 'FOUNDRY_PROJECT_ENDPOINT', value: projectEndpoint }
        { name: 'STORAGE_BLOB_ENDPOINT', value: storage.properties.primaryEndpoints.blob }
      ]
    }
  }
  dependsOn: [containers, reviewQueue, privateDnsGroups, privateZoneLinks]
}

// ---------- Roles ----------
// The Function's host files, code package, review queue, and dry-run results, with its managed identity (no keys).
resource reviewerBlobs 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, reviewer.id, roles.storageBlobDataOwner)
  properties: {
    principalId: reviewer.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataOwner)
  }
}

resource reviewerQueue 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, reviewer.id, roles.storageQueueDataContributor)
  properties: {
    principalId: reviewer.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageQueueDataContributor)
  }
}

// The Function reads the GitHub token and the webhook secret. Nobody else has a role on the vault's data: Bicep writes
// the secrets through Azure Resource Manager.
resource reviewerSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, reviewer.id, roles.keyVaultSecretsUser)
  properties: {
    principalId: reviewer.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
  }
}

// The Function runs code in both pools and calls the agent.
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
output functionAppName string = reviewer.name
output functionHostName string = reviewer.properties.defaultHostName
output keyVaultName string = vault.name
output judgePoolEndpoint string = judgePool.properties.poolManagementEndpoint
output runPoolEndpoint string = runPool.properties.poolManagementEndpoint
output sandboxConnectionId string = sandboxConnection.id
output appInsightsName string = appInsights.name
