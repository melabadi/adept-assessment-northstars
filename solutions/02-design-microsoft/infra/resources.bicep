// Resources for the Design · Microsoft solution (resource-group scope). Everything the demo runs is here, in Azure:
//   - Microsoft Foundry: the project, the chat model, the advisor agents' Foundry IQ connections, and Application
//     Insights for the agents' traces. The agents themselves, the knowledge bases, and the evaluators are data-plane
//     objects that the azd hook (setup_azure.py) publishes from agent.yaml.
//   - Azure AI Search: the approved standards, one knowledge base per operating profile.
//   - Orchestration: an Azure Function (webhook, gate, guarded GitHub writes) and two Logic Apps (the advisor, and the
//     optional re-index and re-evaluate on merge), reachable from GitHub only through the GitHub App's webhook.
//   - Secrets: Key Vault with no public network access (tenant policy), reached by the Function through a private
//     endpoint, as is the Function's storage. No keys anywhere else: Foundry, Search, and storage disable local auth,
//     and the Logic Apps call Foundry and the Function with a managed identity.
param environmentName string
param location string
param searchLocation string
param principalId string
param principalType string
param githubRepository string
param githubAppName string
param modelName string
param modelVersion string
param modelCapacity int
param resourceSeed string
param tags object

var resourceToken = toLower(empty(resourceSeed)
  ? uniqueString(subscription().id, resourceGroup().id, environmentName)
  : uniqueString(subscription().id, resourceGroup().id, environmentName, resourceSeed))
// agent.yaml is the single source for the operating profiles and the index name.
var spec = loadYamlContent('../agent.yaml')
var profiles = map(items(spec.profiles), profile => profile.key)
var knowledgeApiVersion = '2026-08-01-preview'
var roles = {
  foundryUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d' // Foundry User (formerly Azure AI User): create and call agents
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchIndexDataReader: '1407120a-92aa-4202-b7e9-c0e197c71c8f'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  storageBlobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  keyVaultSecretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
  logAnalyticsReader: '73c42c96-874c-492b-b04d-ab87d138a893'
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

var searchEndpoint = 'https://${search.name}.search.windows.net'

// The fallback knowledge tool (agent.yaml knowledge: azure-ai-search) reaches the index through this connection.
resource searchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: spec.search.connection
  properties: {
    category: 'CognitiveSearch'
    target: searchEndpoint
    authType: 'AAD'
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      ResourceId: search.id
    }
  }
  dependsOn: [chatDeployment]
}

// Foundry IQ: each profile's agent reaches its knowledge base's MCP endpoint through a connection that signs in as the
// project's managed identity. setup_azure.py creates the knowledge bases these connections point to.
@batchSize(1)
resource knowledgeConnections 'Microsoft.CognitiveServices/accounts/projects/connections@2025-10-01-preview' = [for profile in profiles: {
  parent: project
  name: 'standards-kb-${profile}'
  properties: {
    category: 'RemoteTool'
    // The connection signs in as the project's identity. Bicep's type data does not list this value yet; ARM accepts it.
    #disable-next-line BCP036
    authType: 'ProjectManagedIdentity'
    target: '${searchEndpoint}/knowledgebases/standards-${profile}/mcp?api-version=${knowledgeApiVersion}'
    isSharedToAll: true
    audience: 'https://search.azure.com/'
    metadata: { ApiType: 'Azure' }
  }
  dependsOn: [searchConnection]
}]

// ---------- Observability: the agents' traces and the Function's logs ----------
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

// Connecting Application Insights to the project turns on server-side tracing of every agent run.
resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'appinsights'
  properties: {
    category: 'AppInsights'
    target: appInsights.id
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: { key: appInsights.properties.ConnectionString }
    metadata: {
      ApiType: 'Azure'
      ResourceId: appInsights.id
    }
  }
  dependsOn: [knowledgeConnections]
}

// ---------- Network: the Function reaches Key Vault and its storage through private endpoints ----------
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-${resourceToken}'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.42.0.0/16'] }
    subnets: [
      {
        name: 'snet-function'
        properties: {
          addressPrefix: '10.42.0.0/26'
          delegations: [{ name: 'flex', properties: { serviceName: 'Microsoft.App/environments' } }]
        }
      }
      {
        name: 'snet-private-endpoints'
        properties: { addressPrefix: '10.42.1.0/27' }
      }
    ]
  }
}

var privateLinks = [
  { name: 'blob', zone: 'privatelink.blob.${environment().suffixes.storage}' }
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
  location: location
  tags: tags
  properties: {
    subnet: { id: vnet.properties.subnets[1].id }
    privateLinkServiceConnections: [
      {
        name: link.name
        properties: {
          privateLinkServiceId: link.name == 'blob' ? storage.id : vault.id
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

// ---------- Storage: the Function's code package and its markers (handled deliveries, answered issues) ----------
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

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for name in ['function-package', 'advisor-state']: {
  parent: blobService
  name: name
  properties: { publicAccess: 'None' }
}]

// ---------- Key Vault: the GitHub App's credentials and the Logic Apps' trigger URLs ----------
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

// ---------- The Function: webhook, gate, and the advisor's only GitHub writes ----------
resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'plan-${resourceToken}'
  location: location
  tags: tags
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

resource logicIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-logic-${resourceToken}'
  location: location
  tags: tags
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
        // Blob only: the Function has no queue or table triggers, and only blob has a private endpoint.
        { name: 'AzureWebJobsStorage__blobServiceUri', value: storage.properties.primaryEndpoints.blob }
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'KEY_VAULT_URI', value: vault.properties.vaultUri }
        { name: 'STORAGE_BLOB_ENDPOINT', value: storage.properties.primaryEndpoints.blob }
        { name: 'GITHUB_REPOSITORY', value: githubRepository }
        { name: 'GITHUB_APP_NAME', value: githubAppName }
        { name: 'AZURE_TENANT_ID', value: tenant().tenantId }
        { name: 'LOGIC_APP_CLIENT_ID', value: logicIdentity.properties.clientId }
        { name: 'LOGIC_APP_PRINCIPAL_ID', value: logicIdentity.properties.principalId }
        { name: 'FOUNDRY_PROJECT_ENDPOINT', value: 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}' }
        { name: 'FOUNDRY_MODEL_DEPLOYMENT', value: chatDeployment.name }
        { name: 'SEARCH_ENDPOINT', value: searchEndpoint }
        { name: 'SEARCH_INDEX', value: spec.search.index }
      ]
    }
  }
  dependsOn: [containers, privateDnsGroups, privateZoneLinks]
}

// ---------- Logic Apps: the orchestration a presenter shows in the run history ----------
var functionBaseUrl = 'https://${functionApp.properties.defaultHostName}'

resource advisorWorkflow 'Microsoft.Logic/workflows@2019-05-01' = {
  name: 'logic-advisor-${resourceToken}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${logicIdentity.id}': {} }
  }
  properties: {
    state: 'Enabled'
    definition: loadJsonContent('workflows/advisor.json')
    parameters: {
      functionBaseUrl: { value: functionBaseUrl }
      responsesUrl: { value: 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}/openai/v1/responses' }
      identityId: { value: logicIdentity.id }
      // Entra issues no token for a managed identity as audience; Storage is one this identity has no role on (advisor_core/auth.py).
      functionAudience: { value: 'https://storage.azure.com/' }
    }
  }
}

resource standardsWorkflow 'Microsoft.Logic/workflows@2019-05-01' = {
  name: 'logic-standards-${resourceToken}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${logicIdentity.id}': {} }
  }
  properties: {
    state: 'Enabled'
    definition: loadJsonContent('workflows/standards.json')
    parameters: {
      functionBaseUrl: { value: functionBaseUrl }
      identityId: { value: logicIdentity.id }
      // Entra issues no token for a managed identity as audience; Storage is one this identity has no role on (advisor_core/auth.py).
      functionAudience: { value: 'https://storage.azure.com/' }
    }
  }
}

// The trigger URLs carry a signature: only Key Vault holds them, and only the Function reads them.
resource advisorWorkflowUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'advisor-workflow-url'
  properties: {
    value: listCallbackUrl('${advisorWorkflow.id}/triggers/When_GitHub_sends_a_design_question', '2019-05-01').value
    contentType: 'text/plain'
  }
}

resource standardsWorkflowUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'standards-workflow-url'
  properties: {
    value: listCallbackUrl('${standardsWorkflow.id}/triggers/When_a_change_to_the_standards_merges', '2019-05-01').value
    contentType: 'text/plain'
  }
}

// ---------- Who may do what ----------
// The presenter publishes agents and syncs the index from azd; the Function does the same on merge and checks answers.
var operators = ['presenter', 'function']

resource operatorFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for key in operators: {
  scope: foundry
  name: guid(foundry.id, key == 'presenter' ? principalId : functionApp.id, roles.foundryUser)
  properties: {
    principalId: key == 'presenter' ? principalId : functionApp.identity.principalId
    principalType: key == 'presenter' ? principalType : 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}]

resource operatorSearchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for key in operators: {
  scope: search
  name: guid(search.id, key == 'presenter' ? principalId : functionApp.id, roles.searchIndexDataContributor)
  properties: {
    principalId: key == 'presenter' ? principalId : functionApp.identity.principalId
    principalType: key == 'presenter' ? principalType : 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor)
  }
}]

resource operatorSearchService 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for key in operators: {
  scope: search
  name: guid(search.id, key == 'presenter' ? principalId : functionApp.id, roles.searchServiceContributor)
  properties: {
    principalId: key == 'presenter' ? principalId : functionApp.identity.principalId
    principalType: key == 'presenter' ? principalType : 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchServiceContributor)
  }
}]

// The presenter reads the agents' traces in Foundry, which queries the Log Analytics workspace.
resource presenterLogReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: logAnalytics
  name: guid(logAnalytics.id, principalId, roles.logAnalyticsReader)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.logAnalyticsReader)
  }
}

// The Function's host storage, code package, and markers, with its managed identity (no shared keys).
resource functionStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, functionApp.id, roles.storageBlobDataOwner)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataOwner)
  }
}

// The Function stores the GitHub App's credentials once (app-manifest flow) and reads them and the trigger URLs.
resource functionSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, functionApp.id, roles.keyVaultSecretsOfficer)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsOfficer)
  }
}

// The Logic Apps call the advisor agents (and nothing else in Foundry).
resource logicFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, logicIdentity.id, roles.foundryUser)
  properties: {
    principalId: logicIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}

// Foundry IQ and the search tool run as Foundry: they only read the index. Current docs name the project's identity
// and earlier ones the account's, so both get the same read access.
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
output searchEndpoint string = searchEndpoint
output functionAppName string = functionApp.name
output keyVaultName string = vault.name
output advisorWorkflowName string = advisorWorkflow.name
output standardsWorkflowName string = standardsWorkflow.name
output appInsightsName string = appInsights.name
