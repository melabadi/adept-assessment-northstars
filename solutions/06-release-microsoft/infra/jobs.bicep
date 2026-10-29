// The release jobs: one image (../Dockerfile, release.py), five steps. Deployed by `azd deploy release`, which builds
// the image in Azure Container Registry and passes it as imageName. Every job runs as the automation identity:
// Container Apps Contributor (revisions, traffic) and Container Apps Jobs Reader (which release steps are running) on
// the resource group, AcrPull on the registry, and the RequestHub app roles its smoke test needs.
param environmentName string
param location string = resourceGroup().location
param imageName string
param containerRegistryName string
param containerAppsEnvironmentName string
@description('Resource id of the identity the jobs run as.')
param identityId string
param identityClientId string
param apiAppName string
param apiIdentifierUri string
@description('Principal id of the Logic App that starts the release job when a build is pushed.')
param triggerPrincipalId string = ''

var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var jobsOperator = 'b9a307c4-5aa3-4b52-ba60-2b17c136cd7b'

// A release builds, gates, and may wait for another step: up to 30 minutes. The others finish in a few minutes.
var steps = [
  { name: 'release', timeout: 1800 }
  { name: 'promote', timeout: 900 }
  { name: 'abort', timeout: 900 }
  { name: 'rollback', timeout: 900 }
  { name: 'drill', timeout: 1800 }
]

var settings = [
  { name: 'AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
  { name: 'AZURE_RESOURCE_GROUP', value: resourceGroup().name }
  { name: 'AZURE_CLIENT_ID', value: identityClientId }
  { name: 'AZURE_CONTAINER_REGISTRY_ENDPOINT', value: registry.properties.loginServer }
  { name: 'API_APP_NAME', value: apiAppName }
  { name: 'API_IDENTIFIER_URI', value: apiIdentifierUri }
]

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: containerRegistryName
}

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: containerAppsEnvironmentName
}

resource jobs 'Microsoft.App/jobs@2025-07-01' = [for step in steps: {
  name: 'caj-${step.name}-${resourceToken}'
  location: location
  // requesthub-release marks the jobs whose executions count as release steps: one runs at a time.
  tags: union({ 'azd-env-name': environmentName, 'requesthub-release': step.name }, step.name == 'release' ? { 'azd-service-name': 'release' } : {})
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  properties: {
    environmentId: containerAppsEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: step.timeout
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ server: registry.properties.loginServer, identity: identityId }]
    }
    template: {
      containers: [{
        name: 'release'
        image: imageName
        args: [step.name]
        env: concat(settings, [{ name: 'RELEASE_STEP', value: step.name }])
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
      }]
    }
  }
}]

// The Logic App may start the release job, and only that job.
resource triggerStartsRelease 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(triggerPrincipalId)) {
  scope: jobs[0]
  name: guid(jobs[0].id, triggerPrincipalId, jobsOperator)
  properties: {
    principalId: triggerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', jobsOperator)
  }
}

output SERVICE_RELEASE_NAME string = jobs[0].name
