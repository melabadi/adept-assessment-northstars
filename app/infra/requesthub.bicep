// RequestHub hosting platform (resource-group scope). Microsoft-track solutions that run the app compose this module
// from their own infra/main.bicep, in their own resource group:
//
//   module app '../../../app/infra/requesthub.bicep' = { scope: rg, params: { ... } }
//
// It creates everything the app needs except the container apps themselves, which `azd deploy` creates from api.bicep
// and worker.bicep so that image, configuration, probes, and authentication ship together as one revision.
extension microsoftGraphV1

@description('azd environment name. Part of resource names and of the Entra app identifier URI.')
param environmentName string

param location string = resourceGroup().location

@description('Object id of the presenter. Receives every RequestHub app role.')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@description('GitHub repository (owner/name) whose workflows sign in to Azure with OIDC. Empty skips the federated credential.')
param githubRepository string = ''

@description('Subject prefix of the repository\'s OIDC tokens when it uses immutable subjects: gh api repos/OWNER/REPO/actions/oidc/customization/sub --jq .sub_claim_prefix')
param githubOidcSubjectPrefix string = ''

@description('GitHub environment whose jobs may use the automation identity, for example develop-microsoft.')
param githubEnvironment string = ''

@description('Extra Azure roles (role definition GUIDs) for the automation identity on this resource group, for example Contributor for release workflows.')
param automationRoleDefinitionIds array = []

@description('Storage shared-key access. Keep false; the Secure solution starts from true to demonstrate the remediation.')
param storageAllowSharedKeyAccess bool = false

@description('PostgreSQL major version.')
param postgresVersion string = '16'

param tags object = {}

var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var apiAppName = 'ca-api-${resourceToken}'
var workerAppName = 'ca-worker-${resourceToken}'
var postgresName = 'psql-${resourceToken}'
var apiIdentifierUri = 'api://${tenant().tenantId}/requesthub-${environmentName}'
var appRoleNames = ['Requester', 'Reviewer', 'Approver', 'Admin']
var automationAppRoleNames = ['Requester', 'Reviewer', 'Approver']
var userImpersonationScopeId = guid(resourceGroup().id, 'requesthub', 'user_impersonation')
var azureCliAppId = '04b07795-8ddb-461a-bbee-02f9e1bf7b46'
// GitHub OIDC tokens use either the classic subject (repo:owner/name) or the immutable one (repo:owner@id/name@id).
var githubSubjectPrefix = empty(githubOidcSubjectPrefix) ? 'repo:${githubRepository}' : githubOidcSubjectPrefix

var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  acrPush: '8311e382-0749-4cb8-b61a-304f252e45ec'
  blobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
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

resource githubEnvironmentCredential 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (!empty(githubRepository) && !empty(githubEnvironment)) {
  parent: automationIdentity
  name: 'github-environment-${githubEnvironment}'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: '${githubSubjectPrefix}:environment:${githubEnvironment}'
    audiences: ['api://AzureADTokenExchange']
  }
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

module postgresAdmin 'modules/postgres-admin.bicep' = {
  name: 'postgres-admin-${resourceToken}'
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
  dependsOn: [postgresAdmin]
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

// ---------- Microsoft Entra app registration for sign-in (Container Apps built-in authentication) ----------
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
    // Lets presenters call the API with `az account get-access-token --scope <identifier uri>/user_impersonation`.
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

resource automationAppRoles 'Microsoft.Graph/appRoleAssignedTo@v1.0' = [for role in automationAppRoleNames: {
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

resource automationAcrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, automationIdentity.id, roles.acrPush)
  properties: { principalId: automationIdentity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPush) }
}

resource automationRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in automationRoleDefinitionIds: {
  name: guid(resourceGroup().id, automationIdentity.id, roleId)
  properties: { principalId: automationIdentity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId) }
}]

output registryLoginServer string = registry.properties.loginServer
output registryName string = registry.name
output containerAppsEnvironmentName string = containerAppsEnvironment.name
output appIdentityId string = appIdentity.id
output appIdentityClientId string = appIdentity.properties.clientId
output appIdentityPrincipalId string = appIdentity.properties.principalId
output appIdentityName string = appIdentity.name
output automationIdentityName string = automationIdentity.name
output automationClientId string = automationIdentity.properties.clientId
output automationPrincipalId string = automationIdentity.properties.principalId
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output appInsightsName string = appInsights.name
output appInsightsId string = appInsights.id
output logAnalyticsName string = logAnalytics.name
output logAnalyticsId string = logAnalytics.id
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
