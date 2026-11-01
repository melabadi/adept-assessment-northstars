// The release's orchestration in Azure, next to RequestHub's platform (app/infra/requesthub.bicep):
//   Event Grid      a system topic on the registry, which fires when a build of the API's repository is pushed
//   Function        the release trigger (../trigger): checks each pushed build's event, then starts the release job
//                   with the image's digest. Flex Consumption, in its own virtual network, with private storage
//   Workbook        the release records the jobs write to Log Analytics, and who started each step
// The jobs are deployed with their image by `azd deploy release` (jobs.bicep). Event Grid's subscription to the function
// (release-on-push.bicep) is created once every service is deployed: see the postdeploy hook in azure.yaml.
param environmentName string
param location string = resourceGroup().location
param tags object = {}
param registryName string
@description('Principal id of the automation identity that runs the release jobs.')
param automationPrincipalId string
param logAnalyticsId string
param apiAppName string
@description('RequestHub\'s Application Insights: the trigger\'s invocations and logs go there too.')
param appInsightsConnectionString string

var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var releaseJobName = 'caj-release-${resourceToken}'
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  storageBlobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
}
// The API's image repository: Event Grid's filter (release-on-push.bicep) and the trigger's check both use it.
var repository = 'requesthub-api'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

// The jobs pull their image, and read which commit a build was made from, with pull rights only.
resource automationAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, automationPrincipalId, roles.acrPull)
  properties: {
    principalId: automationPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}

resource registryEvents 'Microsoft.EventGrid/systemTopics@2022-06-15' = {
  name: 'evgt-registry-${resourceToken}'
  location: location
  tags: tags
  properties: {
    source: registry.id
    topicType: 'Microsoft.ContainerRegistry.Registries'
  }
}

// ---------- The trigger's network: a Flex Consumption app reaches its storage only through a private endpoint ----------
// A Flex Consumption app needs a subnet of its own, which it can't share with the Container Apps environment, so the
// trigger gets its own small virtual network rather than a change to the app's.
resource triggerNetwork 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-release-${resourceToken}'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.41.0.0/24'] }
    subnets: [
      {
        name: 'snet-function'
        properties: {
          addressPrefix: '10.41.0.0/27'
          delegations: [{ name: 'flex', properties: { serviceName: 'Microsoft.App/environments' } }]
        }
      }
      {
        name: 'snet-private-endpoints'
        properties: { addressPrefix: '10.41.0.32/28' }
      }
    ]
  }
}

// The trigger's storage: its code package and the Functions host's state. No shared keys and no public network access,
// as a tenant policy requires: the function reaches it with its managed identity, through the private endpoint.
resource triggerStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'strelease${resourceToken}'
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

resource triggerBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: triggerStorage
  name: 'default'
}

resource triggerPackage 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: triggerBlobService
  name: 'function-package'
  properties: { publicAccess: 'None' }
}

// The app's private DNS zone for Blob storage (requesthub.bicep, storagePrivateEndpoint) holds this account's private
// address too, and answers in the trigger's network. A resource group can hold only one zone with this name.
resource blobZone 'Microsoft.Network/privateDnsZones@2024-06-01' existing = {
  name: 'privatelink.blob.${environment().suffixes.storage}'
}

resource blobZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: blobZone
  name: 'release-trigger-link'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: triggerNetwork.id }
  }
}

resource triggerStorageEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-release-blob-${resourceToken}'
  location: location
  tags: tags
  properties: {
    subnet: { id: triggerNetwork.properties.subnets[1].id }
    privateLinkServiceConnections: [
      {
        name: 'blob'
        properties: { privateLinkServiceId: triggerStorage.id, groupIds: ['blob'] }
      }
    ]
  }
}

resource triggerStorageDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: triggerStorageEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{ name: 'blob', properties: { privateDnsZoneId: blobZone.id } }]
  }
}

// ---------- The trigger: an Azure Function that Event Grid calls once for each pushed build ----------
resource triggerPlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'plan-release-${resourceToken}'
  location: location
  tags: tags
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

// Its managed identity gets Container Apps Jobs Operator on the release job only (jobs.bicep), so it can start that job
// and nothing else. It starts the job only for a push of the API's repository to this registry, named by digest, and
// passes the event's values to the job as values. An event that fails a check starts nothing, and the invocation fails
// with the check's name.
resource trigger 'Microsoft.Web/sites@2024-04-01' = {
  name: 'func-release-${resourceToken}'
  location: location
  tags: union(tags, { 'azd-service-name': 'trigger' })
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: triggerPlan.id
    httpsOnly: true
    virtualNetworkSubnetId: triggerNetwork.properties.subnets[0].id
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${triggerStorage.properties.primaryEndpoints.blob}${triggerPackage.name}'
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
        // Blob only: the trigger has no queue or table triggers, and only blob has a private endpoint.
        { name: 'AzureWebJobsStorage__blobServiceUri', value: triggerStorage.properties.primaryEndpoints.blob }
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
        { name: 'REGISTRY_ID', value: registry.id }
        { name: 'REGISTRY_HOST', value: registry.properties.loginServer }
        { name: 'RELEASE_REPOSITORY', value: repository }
        { name: 'RELEASE_JOB_ID', value: resourceId('Microsoft.App/jobs', releaseJobName) }
      ]
    }
  }
  dependsOn: [triggerStorageDns, blobZoneLink]
}

// The Functions host keeps its state, and the platform its code package, in this account, as the trigger's identity.
resource triggerStorageOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: triggerStorage
  name: guid(triggerStorage.id, trigger.id, roles.storageBlobDataOwner)
  properties: {
    principalId: trigger.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataOwner)
  }
}

resource workbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: guid(resourceGroup().id, 'requesthub-release-records')
  location: location
  tags: tags
  kind: 'shared'
  properties: {
    displayName: 'RequestHub release records'
    category: 'workbook'
    sourceId: logAnalyticsId
    serializedData: replace(replace(replace(replace(loadTextContent('release-records.workbook.json'),
      '__SUBSCRIPTION_ID__', subscription().subscriptionId), '__RESOURCE_GROUP__', resourceGroup().name),
      '__API_APP__', apiAppName), '__LOG_ANALYTICS_ID__', logAnalyticsId)
  }
}

output triggerPrincipalId string = trigger.identity.principalId
output triggerName string = trigger.name
output topicName string = registryEvents.name
output repository string = repository
output releaseJobName string = releaseJobName
output workbookId string = workbook.id
