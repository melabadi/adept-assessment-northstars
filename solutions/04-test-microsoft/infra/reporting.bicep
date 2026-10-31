// Reports every finished load test run to GitHub, from Azure, with one Python Azure Function app (Flex Consumption).
//
// Azure Load Testing's notification rule (created by sync_test.py, because notification rules are data-plane objects)
// sends each finished run of the test to the action group below, which calls the function's HTTP route with a function
// key. The function (function/, with unit tests in test_reporter.py), with its own managed identity:
//   - reads the run from Azure Load Testing (Load Test Reader) and accepts it only if it belongs to this test and
//     ended in the last 60 minutes, so replays and forged calls never post;
//   - queues the report and answers at once; each queued step waits for the run's verdict, then for Application
//     Insights to hold the run's last requests, by queueing the next step with a delay instead of sleeping;
//   - runs function/reporter/report.kql on the workspace (Log Analytics Reader) and writes the report and its verdict;
//   - holds a blob lease while it posts, so one report at a time opens a GitHub Issue for a failing run, comments on it
//     for the next failures, or closes it when a run that started after it opened passes and the report accepts it.
// GitHub access is a fine-grained token that a person creates for this repository only, with Issues read and write, and
// sets with `azd env set GITHUB_ISSUES_TOKEN`. Bicep writes it from a secure parameter into Key Vault, the only place
// that holds it: the deployment history doesn't record it, no app setting or output carries it, the function reads it
// with its own identity (Key Vault Secrets User), and never logs it. Without a token the report is built and logged,
// but not posted.
//
// Network: tenant policy turns off public network access on storage accounts and key vaults, and shared keys on storage,
// so the function reaches its storage (code package, queue, lease) and Key Vault through private endpoints in its own
// virtual network. The blob DNS zone is RequestHub's (app/infra/requesthub.bicep creates it in this resource group, and a
// resource group holds one zone per name); the queue and vault zones are this module's.

param environmentName string
param location string
param tags object = {}

@description('Name of the Azure Load Testing resource whose runs are reported.')
param loadTestName string

@description('Test whose runs are reported; the testId in loadtest/requesthub-journey.yaml.')
param testId string

@description('Log Analytics workspace that holds RequestHub\'s Application Insights data.')
param logAnalyticsName string

@description('GitHub repository, owner/name, where the Issues are opened. Empty: the report is built but not posted.')
param githubRepository string

@secure()
@description('Fine-grained GitHub token for that repository only, with Issues read and write. Empty: nothing is posted.')
param githubToken string

// Same token as app/infra/requesthub.bicep, so every resource in the group shares one suffix.
var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var queueName = 'test-runs'
var roles = {
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  loadTestReader: '3ae3fb29-0000-4ccd-bf80-542e7b26e081'
  logAnalyticsReader: '73c42c96-874c-492b-b04d-ab87d138a893'
  storageBlobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  storageQueueDataContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
}

resource loadTest 'Microsoft.LoadTestService/loadTests@2022-12-01' existing = {
  name: loadTestName
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsName
}

// The function's own logs, in the same workspace, so RequestHub's Application Insights shows only the app.
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-loadtest-${resourceToken}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
  }
}

// ---------- Network: the function reaches its storage through private endpoints ----------
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-loadtest-${resourceToken}'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.41.0.0/16'] }
    subnets: [
      {
        name: 'snet-function'
        properties: {
          addressPrefix: '10.41.0.0/26'
          delegations: [{ name: 'flex', properties: { serviceName: 'Microsoft.App/environments' } }]
        }
      }
      {
        name: 'snet-private-endpoints'
        properties: { addressPrefix: '10.41.1.0/27' }
      }
    ]
  }
}

resource blobZone 'Microsoft.Network/privateDnsZones@2024-06-01' existing = {
  name: 'privatelink.blob.${environment().suffixes.storage}'
}

resource queueZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.queue.${environment().suffixes.storage}'
  location: 'global'
  tags: tags
}

resource blobZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: blobZone
  name: 'vnet-loadtest-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource queueZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: queueZone
  name: 'vnet-loadtest-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource vaultZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.vaultcore.azure.net'
  location: 'global'
  tags: tags
}

resource vaultZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: vaultZone
  name: 'vnet-loadtest-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

var privateLinks = [
  { service: 'blob', zoneId: blobZone.id, target: storage.id }
  { service: 'queue', zoneId: queueZone.id, target: storage.id }
  { service: 'vault', zoneId: vaultZone.id, target: vault.id }
]

resource privateEndpoints 'Microsoft.Network/privateEndpoints@2024-05-01' = [for link in privateLinks: {
  name: 'pe-loadtest-${link.service}-${resourceToken}'
  location: location
  tags: tags
  properties: {
    subnet: { id: vnet.properties.subnets[1].id }
    privateLinkServiceConnections: [
      {
        name: link.service
        properties: { privateLinkServiceId: link.target, groupIds: [link.service] }
      }
    ]
  }
}]

resource privateDnsGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = [for (link, i) in privateLinks: {
  parent: privateEndpoints[i]
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{ name: link.service, properties: { privateDnsZoneId: link.zoneId } }]
  }
}]

// ---------- Storage: the function's code package, its queue of report steps, and the GitHub lease ----------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stloadtest${resourceToken}'
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

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for name in ['function-package', 'reporter']: {
  parent: blobService
  name: name
  properties: { publicAccess: 'None' }
}]

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource queue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queueService
  name: queueName
}

// ---------- Key Vault: the only place that holds the GitHub token ----------
// Bicep writes the secret through Azure Resource Manager (a control-plane write), so the vault needs no public access;
// only the function's identity may read it, through the vault's private endpoint.
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

resource githubTokenSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(githubToken)) {
  parent: vault
  name: 'github-token'
  properties: {
    value: githubToken
    contentType: 'text/plain'
  }
}

// ---------- The function app ----------
resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'plan-loadtest-${resourceToken}'
  location: location
  tags: tags
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: 'func-loadtest-${resourceToken}'
  location: location
  tags: union(tags, { 'azd-service-name': 'reporter' })
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
        instanceMemoryMB: 512
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
        { name: 'LOAD_TESTING_ENDPOINT', value: 'https://${loadTest.properties.dataPlaneURI}' }
        { name: 'TEST_ID', value: testId }
        { name: 'WORKSPACE_ID', value: workspace.properties.customerId }
        { name: 'RESOURCE_GROUP_NAME', value: resourceGroup().name }
        { name: 'QUEUE_NAME', value: queueName }
        { name: 'STORAGE_QUEUE_ENDPOINT', value: storage.properties.primaryEndpoints.queue }
        { name: 'STORAGE_BLOB_ENDPOINT', value: storage.properties.primaryEndpoints.blob }
        { name: 'GITHUB_REPOSITORY', value: githubRepository }
        { name: 'KEY_VAULT_URI', value: vault.properties.vaultUri }
      ]
    }
  }
  dependsOn: [containers, queue, privateDnsGroups, blobZoneLink, queueZoneLink, vaultZoneLink]
}

// ---------- What the function's identity may do ----------
resource storageRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in [roles.storageBlobDataOwner, roles.storageQueueDataContributor]: {
  scope: storage
  name: guid(storage.id, functionApp.id, role)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
  }
}]

resource readRuns 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: loadTest
  name: guid(loadTest.id, functionApp.id, roles.loadTestReader)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.loadTestReader)
  }
}

resource readTelemetry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: workspace
  name: guid(workspace.id, functionApp.id, roles.logAnalyticsReader)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.logAnalyticsReader)
  }
}

resource readGitHubToken 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, functionApp.id, roles.keyVaultSecretsUser)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
  }
}

// ---------- The action group calls the function's route with its own function key ----------
// Bicep publishes no types for function keys; Azure Resource Manager creates the key all the same.
#disable-next-line BCP081
resource actionGroupKey 'Microsoft.Web/sites/host/functionKeys@2023-12-01' = {
  #disable-next-line use-parent-property
  name: '${functionApp.name}/default/actiongroup'
  properties: { name: 'actiongroup' }
  dependsOn: [storageRoles]
}

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-loadtest-${resourceToken}'
  location: 'Global'
  tags: tags
  properties: {
    groupShortName: 'loadtest'
    enabled: true
    azureFunctionReceivers: [
      {
        name: 'report-to-github'
        functionAppResourceId: functionApp.id
        functionName: 'test_run_ended'
        httpTriggerUrl: 'https://${functionApp.properties.defaultHostName}/api/test-run-ended?code=${listKeys('${functionApp.id}/host/default', '2023-12-01').functionKeys.actiongroup}'
        useCommonAlertSchema: false
      }
    ]
  }
  dependsOn: [actionGroupKey]
}

output functionAppName string = functionApp.name
output actionGroupId string = actionGroup.id
