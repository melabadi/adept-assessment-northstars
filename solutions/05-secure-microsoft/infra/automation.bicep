// The posture automation that runs in Azure, next to the app it watches:
// - posture-intake (Logic App): Defender for Cloud's "Trigger logic app" on the recommendation files the GitHub Issue, asks
//   the Foundry agent posture-remediator for the smallest Bicep fix, and opens it as a draft pull request.
// - posture-preview (Logic App): starts the posture-whatif job for a pull request that changes this solution's infra/,
//   whether the intake opened it or a person pushed to it (a repository webhook calls it).
// - posture-whatif (Container Apps job): previews the pull request's Bicep with Azure what-if, posts a sanitized summary
//   on the pull request, and sets the posture/what-if commit status.
// - posture-verify (Logic App, hourly or on demand): after a person deploys the fix, starts an Azure Policy evaluation and
//   records the evidence on the Issue. Defender's own confirmation arrives through workflow automation
//   (posture-defender-healthy, declared next to posture-intake in logic/intake.json).
// GitHub access is one fine-grained token for this repository only, created by a person. It is stored in Logic App
// securestring parameters (never returned by a GET) and a Container Apps job secret, because the tenant forces Key Vault
// public access off and Consumption Logic Apps cannot reach a private vault.
targetScope = 'resourceGroup'

param environmentName string
param location string = resourceGroup().location
param principalId string
@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'
@description('GitHub repository (owner/name).')
param githubRepository string
@secure()
param githubToken string
param automationIdentityName string
param containerAppsEnvironmentName string
param storageAccountId string
param policyAssignmentName string
@description('Chat model for the remediation agent (GlobalStandard deployment).')
param modelName string = 'gpt-5-mini'
param modelVersion string = '2025-08-07'
@description('Model capacity in thousands of tokens per minute.')
param modelCapacity int = 50

var tags = {
  'azd-env-name': environmentName
  solution: '05-secure-microsoft'
}
var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var roles = {
  // Foundry User (formerly Azure AI User): call agents and models in the project.
  foundryUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  // Container Apps Jobs Operator: start and read job executions, nothing else.
  jobsOperator: 'b9a307c4-5aa3-4b52-ba60-2b17c136cd7b'
}
// The control this solution tracks: built-in policy "Storage accounts should use private link" and the Defender for Cloud
// recommendation that reports it, "Storage account should use a private link connection".
var privateLinkPolicyDefinition = '6edd7eda-6dd8-40f7-810d-67160c639cd9'
var privateLinkAssessment = 'cdc78c07-02b0-4af0-1cb2-cb7c672a8b0a'
var marker = 'posture:storage-private-link:${resourceGroup().name}'
var agentName = 'posture-remediator'
var names = {
  intake: 'posture-intake'
  preview: 'posture-preview'
  verify: 'posture-verify'
  job: 'posture-whatif'
}
// The job runs whatif.py from the default branch, never from the pull request it previews: the pull request's Bicep is
// untrusted input, its code is not run. WHATIF_REF exists only to test a branch before it merges.
var jobBootstrap = '''
import os, sys, runpy, tempfile, urllib.parse, urllib.request
repo = os.environ["GITHUB_REPOSITORY"]
ref = urllib.parse.quote(os.environ.get("WHATIF_REF") or "main", safe="")
url = f"https://api.github.com/repos/{repo}/contents/solutions/05-secure-microsoft/whatif.py?ref={ref}"
headers = {"Authorization": "Bearer " + os.environ["POSTURE_GITHUB_TOKEN"], "Accept": "application/vnd.github.raw",
           "User-Agent": "posture-whatif", "X-GitHub-Api-Version": "2022-11-28"}
script = os.path.join(tempfile.mkdtemp(), "whatif.py")
with open(script, "wb") as handle:
    handle.write(urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60).read())
sys.argv = [script, *sys.argv[1:]]
runpy.run_path(script, run_name="__main__")
'''

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: automationIdentityName
}

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: containerAppsEnvironmentName
}

// ---------- Microsoft Foundry: the remediation agent's project and model ----------
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'aif-${resourceToken}'
  location: location
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

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: 'secure'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'AI-SDLC Secure'
    description: 'Remediation agent for cloud posture findings (Secure phase, Microsoft track).'
  }
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: modelName
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
  }
  // Operations on one Foundry account must run one at a time.
  dependsOn: [project]
}

resource presenterFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, principalId, roles.foundryUser)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}

resource automationFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, identity.id, roles.foundryUser)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}

// ---------- The what-if preview job ----------
resource whatifJob 'Microsoft.App/jobs@2025-07-01' = {
  name: names.job
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    environmentId: containerAppsEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1200
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      secrets: [
        { name: 'github-token', value: empty(githubToken) ? 'not-set' : githubToken }
      ]
    }
    template: {
      containers: [
        {
          name: 'whatif'
          image: 'mcr.microsoft.com/azure-cli:2.91.0'
          command: ['python3', '-c', jobBootstrap]
          env: [
            { name: 'POSTURE_GITHUB_TOKEN', secretRef: 'github-token' }
            { name: 'GITHUB_REPOSITORY', value: githubRepository }
            { name: 'WHATIF_REF', value: 'main' }
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'AZURE_RESOURCE_GROUP', value: resourceGroup().name }
            { name: 'AZURE_ENV_NAME', value: environmentName }
            { name: 'AZURE_LOCATION', value: location }
            { name: 'AZURE_PRINCIPAL_ID', value: principalId }
            { name: 'AZURE_PRINCIPAL_TYPE', value: principalType }
          ]
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
    }
  }
}

resource automationJobsOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: whatifJob
  name: guid(whatifJob.id, identity.id, roles.jobsOperator)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.jobsOperator)
  }
}

// ---------- Logic Apps ----------
// The Defender for Cloud recommendation connector needs no credential: Defender calls the Logic App.
resource defenderConnection 'Microsoft.Web/connections@2016-06-01' = {
  name: 'ascassessment'
  location: location
  tags: tags
  properties: {
    displayName: 'Defender for Cloud recommendations'
    api: { id: subscriptionResourceId('Microsoft.Web/locations/managedApis', location, 'ascassessment') }
  }
}

module previewLogic 'logic/preview.json' = {
  name: names.preview
  params: {
    name: names.preview
    location: location
    tags: tags
    identityId: identity.id
    githubRepository: githubRepository
    githubToken: githubToken
    jobId: whatifJob.id
    infraPrefix: 'solutions/05-secure-microsoft/infra/'
  }
}

module intakeLogic 'logic/intake.json' = {
  name: names.intake
  params: {
    name: names.intake
    location: location
    tags: tags
    identityId: identity.id
    githubRepository: githubRepository
    githubToken: githubToken
    connectionId: defenderConnection.id
    managedApiId: defenderConnection.properties.api.id
    resourceGroupName: resourceGroup().name
    resourceGroupId: resourceGroup().id
    storageAccountId: storageAccountId
    assessmentKey: privateLinkAssessment
    policyDefinitionName: privateLinkPolicyDefinition
    foundryProjectEndpoint: 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
    agentName: agentName
    editablePath: 'solutions/05-secure-microsoft/infra/resources.bicep'
    modulePath: 'app/infra/requesthub.bicep'
    previewWorkflowId: previewLogic.outputs.id
    marker: marker
  }
  dependsOn: [automationFoundryUser]
}

module verifyLogic 'logic/verify.json' = {
  name: names.verify
  params: {
    name: names.verify
    location: location
    tags: tags
    identityId: identity.id
    githubRepository: githubRepository
    githubToken: githubToken
    resourceGroupName: resourceGroup().name
    resourceGroupId: resourceGroup().id
    storageAccountId: storageAccountId
    assessmentKey: privateLinkAssessment
    policyDefinitionName: privateLinkPolicyDefinition
    policyAssignmentName: policyAssignmentName
    marker: marker
  }
}

output foundryProjectEndpoint string = 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
output foundryModelDeployment string = model.name
output agentName string = agentName
output previewWorkflowName string = names.preview
output intakeWorkflowName string = names.intake
output verifyWorkflowName string = names.verify
output whatifJobName string = whatifJob.name
