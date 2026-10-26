// RequestHub shared baseline (resource-group scope).
// Container apps themselves are deploy-time modules (api.bicep, worker.bicep) so each `azd deploy` ships image + config together.
extension microsoftGraphV1

param environmentName string
param location string
param aiLocation string
param searchLocation string
param principalId string
param principalType string
param githubRepository string
param modelName string
param modelVersion string
param modelCapacity int
param storageAllowSharedKeyAccess bool
param postgresVersion string
param tags object

var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var apiAppName = 'ca-api-${resourceToken}'
var workerAppName = 'ca-worker-${resourceToken}'
var postgresName = 'psql-${resourceToken}'
var apiIdentifierUri = 'api://${tenant().tenantId}/requesthub-${environmentName}'
var appRoleNames = ['Requester', 'Reviewer', 'Approver', 'Admin']
var automationRoleNames = ['Requester', 'Reviewer', 'Approver']
var userImpersonationScopeId = guid(resourceGroup().id, 'requesthub', 'user_impersonation')
var azureCliAppId = '04b07795-8ddb-461a-bbee-02f9e1bf7b46'

var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  acrPush: '8311e382-0749-4cb8-b61a-304f252e45ec'
  blobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  contributor: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
  resourcePolicyContributor: '36243c78-bf99-498c-9df9-86d9f8d28608'
  azureAiUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchIndexDataReader: '1407120a-92aa-4202-b7e9-c0e197c71c8f'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  loadTestContributor: '749a398d-560b-491b-bb21-08924219302e'
}

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

// ---------- Network (private PostgreSQL) ----------
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-${resourceToken}'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.40.0.0/16'] }
    subnets: [
      {
        name: 'snet-apps'
        properties: {
          addressPrefix: '10.40.0.0/23'
          delegations: [{ name: 'aca', properties: { serviceName: 'Microsoft.App/environments' } }]
        }
      }
      {
        name: 'snet-postgres'
        properties: {
          addressPrefix: '10.40.2.0/28'
          delegations: [{ name: 'pg', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } }]
        }
      }
    ]
  }
}

resource postgresDns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: '${postgresName}.private.postgres.database.azure.com'
  location: 'global'
  tags: tags
}

resource postgresDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: postgresDns
  name: 'vnet-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

// ---------- Identities ----------
resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-app-${resourceToken}'
  location: location
  tags: tags
}

@description('Used by GitHub Actions through OIDC (no stored secrets).')
resource automationIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-github-${resourceToken}'
  location: location
  tags: tags
}

resource githubEnvironmentCredential 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (!empty(githubRepository)) {
  parent: automationIdentity
  name: 'github-environment-azure-demo'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepository}:environment:azure-demo'
    audiences: ['api://AzureADTokenExchange']
  }
}

resource githubMainCredential 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (!empty(githubRepository)) {
  parent: automationIdentity
  name: 'github-branch-main'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepository}:ref:refs/heads/main'
    audiences: ['api://AzureADTokenExchange']
  }
  dependsOn: [githubEnvironmentCredential]
}

// ---------- Container registry ----------
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'cr${resourceToken}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

// ---------- Storage (attachments) ----------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${resourceToken}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: storageAllowSharedKeyAccess
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource attachmentsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'attachments'
  properties: { publicAccess: 'None' }
}

// ---------- PostgreSQL (private network, Microsoft Entra authentication only) ----------
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: postgresName
  location: location
  tags: tags
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: postgresVersion
    storage: { storageSizeGB: 32, autoGrow: 'Disabled' }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: {
      delegatedSubnetResourceId: vnet.properties.subnets[1].id
      privateDnsZoneArmResourceId: postgresDns.id
      publicNetworkAccess: 'Disabled'
    }
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Disabled'
      tenantId: tenant().tenantId
    }
  }
  dependsOn: [postgresDnsLink]
}

module postgresAdminModule 'modules/postgres-admin.bicep' = {
  name: 'postgres-admin'
  params: {
    postgresName: postgres.name
    principalId: appIdentity.properties.principalId
    principalName: appIdentity.name
  }
}

resource postgresDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'requesthub'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
  dependsOn: [postgresAdminModule]
}

// ---------- Container Apps environment ----------
resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${resourceToken}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: vnet.properties.subnets[0].id
      internal: false
    }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    zoneRedundant: false
  }
}

// ---------- Microsoft Foundry ----------
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
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

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: 'requesthub'
  location: aiLocation
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'RequestHub AI-SDLC demos'
    description: 'Agents used by the Plan, Design, and Develop phases (Microsoft track).'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: modelName
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
  }
  // Operations on one Foundry account must be serialized.
  dependsOn: [foundryProject]
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: 'text-embedding-3-small'
  sku: { name: 'GlobalStandard', capacity: 50 }
  properties: {
    model: { format: 'OpenAI', name: 'text-embedding-3-small', version: '1' }
  }
  dependsOn: [chatDeployment]
}

// ---------- Azure AI Search (Design phase standards index) ----------
resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: 'srch-${resourceToken}'
  location: searchLocation
  tags: tags
  sku: { name: 'basic' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    semanticSearch: 'free'
    disableLocalAuth: true
    publicNetworkAccess: 'enabled'
  }
}

resource searchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: foundryProject
  name: 'standards-search'
  properties: {
    category: 'CognitiveSearch'
    target: 'https://${search.name}.search.windows.net'
    authType: 'AAD'
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      ResourceId: search.id
    }
  }
}

// ---------- Azure Load Testing (Test phase) ----------
resource loadTest 'Microsoft.LoadTestService/loadTests@2022-12-01' = {
  name: 'lt-${resourceToken}'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    description: 'RequestHub performance tests (Test phase, Microsoft track).'
  }
}

// ---------- Microsoft Entra app registration for RequestHub sign-in (Container Apps built-in auth) ----------
resource apiApplication 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: 'requesthub-${environmentName}-${resourceToken}'
  displayName: 'RequestHub (${environmentName})'
  signInAudience: 'AzureADMyOrg'
  identifierUris: [apiIdentifierUri]
  api: {
    requestedAccessTokenVersion: 2
    oauth2PermissionScopes: [
      {
        id: userImpersonationScopeId
        value: 'user_impersonation'
        type: 'User'
        isEnabled: true
        adminConsentDisplayName: 'Access RequestHub'
        adminConsentDescription: 'Allows the app to call RequestHub on behalf of the signed-in user.'
        userConsentDisplayName: 'Access RequestHub'
        userConsentDescription: 'Allows the app to call RequestHub on your behalf.'
      }
    ]
    preAuthorizedApplications: [
      {
        appId: azureCliAppId
        delegatedPermissionIds: [userImpersonationScopeId]
      }
    ]
  }
  appRoles: [for role in appRoleNames: {
    id: guid(resourceGroup().id, 'requesthub-role', role)
    value: 'RequestHub.${role}'
    displayName: role
    description: 'RequestHub ${role}'
    allowedMemberTypes: ['User', 'Application']
    isEnabled: true
  }]
  web: {
    redirectUris: ['https://${apiAppName}.${containerAppsEnvironment.properties.defaultDomain}/.auth/login/aad/callback']
    implicitGrantSettings: { enableIdTokenIssuance: true }
  }
  requiredResourceAccess: [
    {
      resourceAppId: '00000003-0000-0000-c000-000000000000'
      resourceAccess: [{ id: 'e1fe6dd8-ba31-4d61-89e7-88639da4683d', type: 'Scope' }]
    }
  ]
}

resource apiServicePrincipal 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: apiApplication.appId
}

resource presenterAppRoles 'Microsoft.Graph/appRoleAssignedTo@v1.0' = [for role in appRoleNames: if (principalType == 'User') {
  appRoleId: guid(resourceGroup().id, 'requesthub-role', role)
  principalId: principalId
  resourceId: apiServicePrincipal.id
}]

resource automationAppRoles 'Microsoft.Graph/appRoleAssignedTo@v1.0' = [for role in automationRoleNames: {
  appRoleId: guid(resourceGroup().id, 'requesthub-role', role)
  principalId: automationIdentity.properties.principalId
  resourceId: apiServicePrincipal.id
}]

// ---------- Role assignments ----------
resource appAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, appIdentity.id, roles.acrPull)
  properties: { principalId: appIdentity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull) }
}

resource appBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, appIdentity.id, roles.blobDataContributor)
  properties: { principalId: appIdentity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobDataContributor) }
}

resource appFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, appIdentity.id, roles.azureAiUser)
  properties: { principalId: appIdentity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.azureAiUser) }
}

resource automationContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, automationIdentity.id, roles.contributor)
  properties: { principalId: automationIdentity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.contributor) }
}

resource automationPolicy 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, automationIdentity.id, roles.resourcePolicyContributor)
  properties: { principalId: automationIdentity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.resourcePolicyContributor) }
}

resource automationAcrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, automationIdentity.id, roles.acrPush)
  properties: { principalId: automationIdentity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPush) }
}

// Data-plane roles for the presenter and for GitHub automation. Loop keys are static; principal ids resolve at deploy time.
var dataPlaneUsers = ['presenter', 'automation']

resource foundryUserRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for key in dataPlaneUsers: {
  scope: foundry
  name: guid(foundry.id, key == 'presenter' ? principalId : automationIdentity.id, roles.azureAiUser)
  properties: {
    principalId: key == 'presenter' ? principalId : automationIdentity.properties.principalId
    principalType: key == 'presenter' ? principalType : 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.azureAiUser)
  }
}]

resource searchDataRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for key in dataPlaneUsers: {
  scope: search
  name: guid(search.id, key == 'presenter' ? principalId : automationIdentity.id, roles.searchIndexDataContributor)
  properties: {
    principalId: key == 'presenter' ? principalId : automationIdentity.properties.principalId
    principalType: key == 'presenter' ? principalType : 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor)
  }
}]

resource searchServiceRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for key in dataPlaneUsers: {
  scope: search
  name: guid(search.id, key == 'presenter' ? principalId : automationIdentity.id, roles.searchServiceContributor)
  properties: {
    principalId: key == 'presenter' ? principalId : automationIdentity.properties.principalId
    principalType: key == 'presenter' ? principalType : 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchServiceContributor)
  }
}]

resource projectSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, foundryProject.id, roles.searchIndexDataReader)
  properties: { principalId: foundryProject.identity.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataReader) }
}

resource projectSearchService 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, foundryProject.id, roles.searchServiceContributor)
  properties: { principalId: foundryProject.identity.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchServiceContributor) }
}

resource loadTestRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for key in dataPlaneUsers: {
  scope: loadTest
  name: guid(loadTest.id, key == 'presenter' ? principalId : automationIdentity.id, roles.loadTestContributor)
  properties: {
    principalId: key == 'presenter' ? principalId : automationIdentity.properties.principalId
    principalType: key == 'presenter' ? principalType : 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.loadTestContributor)
  }
}]

output registryLoginServer string = registry.properties.loginServer
output registryName string = registry.name
output containerAppsEnvironmentName string = containerAppsEnvironment.name
output appIdentityId string = appIdentity.id
output appIdentityClientId string = appIdentity.properties.clientId
output appIdentityName string = appIdentity.name
output automationClientId string = automationIdentity.properties.clientId
output automationPrincipalId string = automationIdentity.properties.principalId
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output appInsightsName string = appInsights.name
output logAnalyticsName string = logAnalytics.name
output logAnalyticsCustomerId string = logAnalytics.properties.customerId
output postgresHost string = '${postgres.name}.postgres.database.azure.com'
output postgresDatabase string = postgresDatabase.name
output storageAccountName string = storage.name
output storageBlobEndpoint string = storage.properties.primaryEndpoints.blob
output apiAppName string = apiAppName
output workerAppName string = workerAppName
output apiUrl string = 'https://${apiAppName}.${containerAppsEnvironment.properties.defaultDomain}'
output apiClientId string = apiApplication.appId
output apiIdentifierUri string = apiIdentifierUri
output foundryAccountName string = foundry.name
output foundryProjectName string = foundryProject.name
output foundryProjectEndpoint string = 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${foundryProject.name}'
output foundryModelDeployment string = chatDeployment.name
output searchName string = search.name
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output searchConnectionName string = searchConnection.name
output loadTestName string = loadTest.name
