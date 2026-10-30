// RequestHub's hosting platform and the Azure Policy assignment that audits it, in this solution's resource group.
// main.bicep deploys this file. This is the file a posture fix changes, so the Azure what-if preview of a pull request
// (whatif.py, run by the posture-whatif Container Apps job) previews exactly this file.
targetScope = 'resourceGroup'

@description('azd environment name. Part of resource names and of the Entra app identifier URI.')
param environmentName string

param location string = resourceGroup().location

@description('Object id of the presenter. Receives every RequestHub app role.')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

// Computed here rather than passed in, so a resource-group what-if of this file reproduces `azd provision` exactly.
var tags = {
  'azd-env-name': environmentName
  solution: '05-secure-microsoft'
}
var roles = {
  reader: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
  // Policy Enrollments Contributor is the smallest built-in role with Microsoft.PolicyInsights/* (query compliance, start an
  // evaluation) and Microsoft.Resources/deployments/* (what-if). Those also allow attestations, deployments (which still
  // need write access to every resource they create or change), and remediation tasks, which run with the identity of a
  // DeployIfNotExists or Modify policy assignment, inherited ones included, and can change the resources it covers. The
  // identity itself has no write access to resources, policy assignments, or exemptions: it can find, preview, and verify
  // a fix, and a person deploys it.
  policyEnrollmentsContributor: '285ce6d6-fa11-43bd-94ef-42a9b3740bfd'
}

module app '../../../app/infra/requesthub.bicep' = {
  name: 'requesthub'
  params: {
    environmentName: environmentName
    location: location
    principalId: principalId
    principalType: principalType
    // The automation identity is used only inside Azure, by the posture Logic Apps and the what-if job: no GitHub
    // federation, no registry push, no RequestHub app role. Reader and Policy Enrollments Contributor on this group.
    automationRoleDefinitionIds: [roles.reader, roles.policyEnrollmentsContributor]
    automationCanPushImages: false
    automationAppRoleNames: []
    tags: tags
    // posture:editable-begin. The posture-remediator agent may change only the lines between these two markers.
    // Without a private endpoint, RequestHub reaches Blob storage through the account's public endpoint. Where an Azure
    // Policy closes public endpoints, as in many organizations, RequestHub cannot reach the account at all.
    storagePrivateEndpoint: false
    // posture:editable-end
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

output policyAssignmentName string = storagePrivateLinkPolicy.name
output policyAssignmentId string = storagePrivateLinkPolicy.id
output storageAccountId string = resourceId('Microsoft.Storage/storageAccounts', app.outputs.storageAccountName)
output automationIdentityName string = app.outputs.automationIdentityName
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
