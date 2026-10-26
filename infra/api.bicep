// Deploy-time module for the RequestHub API + web UI. `azd deploy api` builds the image in ACR and applies this file,
// so image, configuration, probes, and authentication ship together as one revision.
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
param blobEndpoint string
param apiClientId string
param apiIdentifierUri string
param foundryProjectEndpoint string = ''
@allowed(['SampleRules', 'Foundry'])
param triageProvider string = 'SampleRules'
param triageAgentName string = 'requesthub-triage'
param industry string = 'general'
param buildSha string = 'local'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: containerRegistryName
}

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: containerAppsEnvironmentName
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: {
    'azd-env-name': environmentName
    'azd-service-name': 'api'
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    environmentId: containerAppsEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      // Multiple revisions let the Release phase run candidate, promote, and rollback exercises.
      activeRevisionsMode: 'Multiple'
      maxInactiveRevisions: 10
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
        traffic: [{ latestRevision: true, weight: 100 }]
      }
      registries: [{ server: registry.properties.loginServer, identity: identityId }]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: imageName
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'ASPNETCORE_ENVIRONMENT', value: 'Production' }
            { name: 'ConnectionStrings__RequestHub', value: 'Host=${postgresHost};Database=${postgresDatabase};Username=${identityName};Ssl Mode=Require' }
            { name: 'Database__UseEntraAuth', value: 'true' }
            { name: 'AZURE_CLIENT_ID', value: identityClientId }
            { name: 'Auth__Mode', value: 'EasyAuth' }
            { name: 'Storage__Provider', value: 'Blob' }
            { name: 'Storage__BlobServiceUri', value: blobEndpoint }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'OTEL_SERVICE_NAME', value: 'requesthub-api' }
            { name: 'Demo__Industry', value: industry }
            { name: 'Demo__AllowReset', value: 'true' }
            { name: 'Triage__Provider', value: triageProvider }
            { name: 'Foundry__ProjectEndpoint', value: foundryProjectEndpoint }
            { name: 'Foundry__AgentName', value: triageAgentName }
            { name: 'BUILD_SHA', value: buildSha }
          ]
          probes: [
            { type: 'Startup', httpGet: { path: '/health/live', port: 8080 }, initialDelaySeconds: 2, periodSeconds: 3, failureThreshold: 30 }
            { type: 'Liveness', httpGet: { path: '/health/live', port: 8080 }, periodSeconds: 10, failureThreshold: 3 }
            { type: 'Readiness', httpGet: { path: '/health/ready', port: 8080 }, periodSeconds: 5, timeoutSeconds: 3, failureThreshold: 3 }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [{ name: 'http', http: { metadata: { concurrentRequests: '50' } } }]
      }
    }
  }
}

// Container Apps built-in authentication with Microsoft Entra ID. The platform validates sessions and bearer tokens;
// the API enforces app roles and department access itself.
resource auth 'Microsoft.App/containerApps/authConfigs@2024-03-01' = {
  parent: api
  name: 'current'
  properties: {
    platform: { enabled: true }
    globalValidation: {
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
      excludedPaths: ['/health/live', '/health/ready', '/api/meta']
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: apiClientId
          openIdIssuer: '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [apiClientId, apiIdentifierUri]
        }
      }
    }
    login: { preserveUrlFragmentsForLogins: true }
  }
}

output SERVICE_API_URI string = 'https://${api.properties.configuration.ingress.fqdn}'
output SERVICE_API_NAME string = api.name
