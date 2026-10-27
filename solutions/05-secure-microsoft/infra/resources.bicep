// Everything in this solution's resource group: RequestHub's hosting platform and the Azure Policy assignment that audits
// it. main.bicep deploys this file. A change to it is previewed with a resource-group what-if (nothing is deployed):
//   python .github/skills/infrastructure-remediation/whatif.py --expect Microsoft.Storage/storageAccounts ...
targetScope = 'resourceGroup'

@description('azd environment name. Part of resource names and of the Entra app identifier URI.')
param environmentName string

param location string = resourceGroup().location

@description('Object id of the presenter. Receives every RequestHub app role.')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@description('GitHub repository (owner/name) whose workflows sign in to Azure with OIDC.')
param githubRepository string = ''

@description('OIDC subject prefix for repositories that use immutable subjects.')
param githubOidcSubjectPrefix string = ''

// Computed here rather than passed in, so a resource-group what-if of this file reproduces `azd provision` exactly.
var tags = {
  'azd-env-name': environmentName
  solution: '05-secure-microsoft'
}
var githubEnvironment = 'secure-microsoft'
var roles = {
  reader: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
  // Policy Enrollments Contributor is the smallest built-in role with Microsoft.PolicyInsights/* (query compliance, start an
  // evaluation) and Microsoft.Resources/deployments/* (what-if). It cannot change resources, policy assignments, or
  // exemptions, so the GitHub workflows can find, preview, and verify, but never deploy.
  policyEnrollmentsContributor: '285ce6d6-fa11-43bd-94ef-42a9b3740bfd'
}

module app '../../../app/infra/requesthub.bicep' = {
  name: 'requesthub'
  params: {
    environmentName: environmentName
    location: location
    principalId: principalId
    principalType: principalType
    githubRepository: githubRepository
    githubOidcSubjectPrefix: githubOidcSubjectPrefix
    githubEnvironment: githubEnvironment
    automationRoleDefinitionIds: [roles.reader, roles.policyEnrollmentsContributor]
    // Without a private endpoint, RequestHub reaches Blob storage through the account's public endpoint, which is open to
    // the internet. Where Azure Policy closes public endpoints (many organizations do), attachment uploads fail instead.
    // This solution starts without it, so Azure Policy and Defender for Cloud have a real finding to report.
    storagePrivateEndpoint: false
    tags: tags
  }
}

// Built-in definition "Storage accounts should use private link", pinned to major version 2 and assigned to this resource
// group only. AuditIfNotExists reports an account without an approved private endpoint; it never blocks a deployment.
// Defender for Cloud reports the same control through the Microsoft cloud security benchmark, on its own schedule.
resource storagePrivateLinkPolicy 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'requesthub-storage-private-link'
  properties: {
    displayName: 'RequestHub: storage accounts should use private link'
    description: 'Audits the RequestHub storage account in this resource group. Remediate in Bicep (solutions/05-secure-microsoft/infra/resources.bicep), never with an exemption.'
    policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', '6edd7eda-6dd8-40f7-810d-67160c639cd9')
    definitionVersion: '2.*.*'
    enforcementMode: 'Default'
    parameters: {
      effect: { value: 'AuditIfNotExists' }
    }
    nonComplianceMessages: [
      { message: 'Reach the storage account through a private endpoint in the app\'s virtual network and close its public endpoint.' }
    ]
  }
}

output githubEnvironment string = githubEnvironment
output policyAssignmentName string = storagePrivateLinkPolicy.name
output storageAccountName string = app.outputs.storageAccountName
output registryLoginServer string = app.outputs.registryLoginServer
output registryName string = app.outputs.registryName
output containerAppsEnvironmentName string = app.outputs.containerAppsEnvironmentName
output appIdentityId string = app.outputs.appIdentityId
output appIdentityClientId string = app.outputs.appIdentityClientId
output appIdentityName string = app.outputs.appIdentityName
output appInsightsConnectionString string = app.outputs.appInsightsConnectionString
output postgresHost string = app.outputs.postgresHost
output postgresDatabase string = app.outputs.postgresDatabase
output storageBlobEndpoint string = app.outputs.storageBlobEndpoint
output apiAppName string = app.outputs.apiAppName
output workerAppName string = app.outputs.workerAppName
output apiUrl string = app.outputs.apiUrl
output apiClientId string = app.outputs.apiClientId
output apiIdentifierUri string = app.outputs.apiIdentifierUri
output automationClientId string = app.outputs.automationClientId
