// Deploy-time module for the RequestHub notification worker (no ingress).
param environmentName string
param location string = resourceGroup().location
param name string
param imageName string
param containerRegistryName string
param containerAppsEnvironmentName string
param identityId string
param identityClientId string
param identityName string
param appInsightsConnectionString string
param postgresHost string
param postgresDatabase string
param buildSha string = 'local'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: containerRegistryName
}

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: containerAppsEnvironmentName
}

resource worker 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: {
    'azd-env-name': environmentName
    'azd-service-name': 'worker'
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    environmentId: containerAppsEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [{ server: registry.properties.loginServer, identity: identityId }]
    }
    template: {
      containers: [
        {
          name: 'worker'
          image: imageName
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            { name: 'ASPNETCORE_ENVIRONMENT', value: 'Production' }
            { name: 'ConnectionStrings__RequestHub', value: 'Host=${postgresHost};Database=${postgresDatabase};Username=${identityName};Ssl Mode=Require' }
            { name: 'Database__UseEntraAuth', value: 'true' }
            { name: 'AZURE_CLIENT_ID', value: identityClientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'OTEL_SERVICE_NAME', value: 'requesthub-worker' }
            { name: 'BUILD_SHA', value: buildSha }
          ]
          probes: [
            { type: 'Liveness', httpGet: { path: '/health/live', port: 8080 }, periodSeconds: 15, failureThreshold: 3 }
            { type: 'Readiness', httpGet: { path: '/health/ready', port: 8080 }, periodSeconds: 10, timeoutSeconds: 3, failureThreshold: 3 }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

output SERVICE_WORKER_NAME string = worker.name
