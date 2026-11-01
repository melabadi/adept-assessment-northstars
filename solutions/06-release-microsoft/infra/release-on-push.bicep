// Event Grid's subscription on the registry's system topic: each push of the API's repository, except :main, goes to
// the release trigger function, one event per call. Event Grid checks that the function exists and reads its key
// itself, so nothing here holds a key, and this deploys after the function's code: azd's postdeploy hook (azure.yaml)
// runs it once every service is deployed, with values from the azd environment (outputs of main.bicep).
param topicName string
param triggerName string
@minLength(1)
param repository string

resource registryEvents 'Microsoft.EventGrid/systemTopics@2022-06-15' existing = {
  name: topicName
}

resource trigger 'Microsoft.Web/sites@2024-04-01' existing = {
  name: triggerName
}

resource releaseOnPush 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2022-06-15' = {
  parent: registryEvents
  name: 'release-on-push'
  properties: {
    destination: {
      endpointType: 'AzureFunction'
      properties: {
        resourceId: '${trigger.id}/functions/release_on_push'
        maxEventsPerBatch: 1
        preferredBatchSizeInKilobytes: 64
      }
    }
    filter: {
      includedEventTypes: ['Microsoft.ContainerRegistry.ImagePushed']
      subjectBeginsWith: '${repository}:'
      // Each build is pushed as <repository>:<commit> and <repository>:main; only the commit tag starts a release.
      advancedFilters: [
        { operatorType: 'StringNotIn', key: 'data.target.tag', values: ['main'] }
      ]
    }
    eventDeliverySchema: 'EventGridSchema'
    // A failed invocation is delivered again, up to five attempts in an hour: an Azure error retries by itself. Event
    // Grid delivers at least once, so a push can arrive twice; only the release job execution it started first may
    // release it.
    retryPolicy: { maxDeliveryAttempts: 5, eventTimeToLiveInMinutes: 60 }
  }
}
