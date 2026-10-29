// The release's orchestration in Azure, next to RequestHub's platform (app/infra/requesthub.bicep):
//   Event Grid      fires when a build of requesthub-api is pushed to the registry (any tag except main)
//   Logic App       answers Event Grid's validation handshake, then starts the release job with the pushed digest
//   Workbook        the release records the jobs write to Log Analytics, and who started each step
// The jobs themselves are deployed with their image by `azd deploy release` (jobs.bicep).
param environmentName string
param location string = resourceGroup().location
param tags object = {}
param registryName string
@description('Principal id of the automation identity that runs the release jobs.')
param automationPrincipalId string
param logAnalyticsId string
param apiAppName string

var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var releaseJobName = 'caj-release-${resourceToken}'
var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

// The jobs pull their image, and read which commit a build was made from, with pull rights only.
resource automationAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, automationPrincipalId, acrPull)
  properties: {
    principalId: automationPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
  }
}

// Its managed identity gets Container Apps Jobs Operator on the release job only (jobs.bicep), so it can start that
// job and nothing else.
resource trigger 'Microsoft.Logic/workflows@2019-05-01' = {
  name: 'logic-release-${resourceToken}'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    state: 'Enabled'
    definition: loadJsonContent('release-trigger.json')
    parameters: {
      releaseJobId: { value: resourceId('Microsoft.App/jobs', releaseJobName) }
    }
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

// Creating the subscription makes Event Grid send a validation event; the Logic App answers it.
resource releaseOnPush 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2022-06-15' = {
  parent: registryEvents
  name: 'release-on-push'
  properties: {
    destination: {
      endpointType: 'WebHook'
      properties: {
        endpointUrl: listCallbackUrl('${trigger.id}/triggers/manual', '2019-05-01').value
        maxEventsPerBatch: 1
        preferredBatchSizeInKilobytes: 64
      }
    }
    filter: {
      includedEventTypes: ['Microsoft.ContainerRegistry.ImagePushed']
      subjectBeginsWith: 'requesthub-api:'
      // Each build is pushed as requesthub-api:<commit> and requesthub-api:main; one release per build.
      advancedFilters: [
        { operatorType: 'StringNotIn', key: 'data.target.tag', values: ['main'] }
      ]
    }
    eventDeliverySchema: 'EventGridSchema'
    retryPolicy: { maxDeliveryAttempts: 5, eventTimeToLiveInMinutes: 60 }
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
output releaseJobName string = releaseJobName
output workbookId string = workbook.id
