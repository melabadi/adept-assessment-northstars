// The posture automation that runs in Azure, next to the app it watches:
// - posture-intake (Logic App, three steps): Defender for Cloud sends a recommendation only to a Logic App, from "Trigger
//   logic app" on the recommendation or from its workflow automation posture-defender-healthy (logic/intake.json). It
//   keeps the resource, the recommendation, its status, and the time, and forwards them to the Function, one at a time.
// - The posture Function app (Python, Flex Consumption, ../function): intake files the GitHub Issue, asks the Foundry
//   agent posture-remediator for the smallest Bicep fix, checks it, and opens it as a draft pull request; preview starts
//   the what-if job for a pull request (a repository webhook calls it); verify, every hour, records the evidence once a
//   person has deployed the fix, and closes the Issue.
// - posture-whatif (Container Apps job): previews the pull request's Bicep with Azure what-if, posts a sanitized summary
//   on the pull request, and sets the posture/what-if commit status.
// The Function runs in its own virtual network and reaches its storage account and Key Vault through private endpoints:
// the tenant forces public network access off on both. GitHub access is one fine-grained token for this repository only,
// created by a person. Key Vault holds it for the Function, and a Container Apps secret for the job.
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
@secure()
@description('The secret GitHub signs the repository webhook\'s deliveries with. The preprovision hook generates it.')
param webhookSecret string
param automationIdentityName string
param containerAppsEnvironmentName string
param storageAccountId string
param policyAssignmentName string
param appInsightsConnectionString string
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
  reader: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
  // Query compliance and start an evaluation (see resources.bicep for everything else this role allows).
  policyEnrollmentsContributor: '285ce6d6-fa11-43bd-94ef-42a9b3740bfd'
  storageBlobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
}
// The control this solution tracks: built-in policy "Storage accounts should use private link" and the Defender for Cloud
// recommendation that reports it, "Storage account should use a private link connection".
var privateLinkPolicyDefinition = '6edd7eda-6dd8-40f7-810d-67160c639cd9'
var privateLinkAssessment = 'cdc78c07-02b0-4af0-1cb2-cb7c672a8b0a'
var marker = 'posture:storage-private-link:${resourceGroup().name}'
var agentName = 'posture-remediator'
var names = {
  intake: 'posture-intake'
  job: 'posture-whatif'
  function: 'func-posture-${resourceToken}'
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

var foundryProjectEndpoint = 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'

resource presenterFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, principalId, roles.foundryUser)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}

// ---------- The what-if preview job (the automation identity: Reader and Policy Enrollments Contributor only) ----------
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

// ---------- Network: the Function reaches its storage and Key Vault through private endpoints ----------
// Its own virtual network, apart from RequestHub's. The blob zone is the one a posture fix also declares for RequestHub
// (app/infra/requesthub.bicep, same name and tags): the fix links it to RequestHub's network and adds its record.
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-posture-${resourceToken}'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.41.0.0/16'] }
    subnets: [
      {
        name: 'snet-function'
        properties: {
          addressPrefix: '10.41.0.0/26'
          delegations: [{ name: 'flex', properties: { serviceName: 'Microsoft.App/environments' } }]
        }
      }
      {
        name: 'snet-private-endpoints'
        properties: { addressPrefix: '10.41.1.0/27' }
      }
    ]
  }
}

var privateLinks = [
  { name: 'blob', zone: 'privatelink.blob.${environment().suffixes.storage}' }
  { name: 'vault', zone: 'privatelink.vaultcore.azure.net' }
]

resource privateZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for link in privateLinks: {
  name: link.zone
  location: 'global'
  tags: tags
}]

resource privateZoneLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (link, i) in privateLinks: {
  parent: privateZones[i]
  name: 'posture-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}]

resource privateEndpoints 'Microsoft.Network/privateEndpoints@2024-05-01' = [for link in privateLinks: {
  name: 'pe-posture-${link.name}-${resourceToken}'
  location: location
  tags: tags
  properties: {
    subnet: { id: vnet.properties.subnets[1].id }
    privateLinkServiceConnections: [
      {
        name: link.name
        properties: {
          privateLinkServiceId: link.name == 'blob' ? functionStorage.id : vault.id
          groupIds: [link.name]
        }
      }
    ]
  }
}]

resource privateDnsGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = [for (link, i) in privateLinks: {
  parent: privateEndpoints[i]
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{ name: link.name, properties: { privateDnsZoneId: privateZones[i].id } }]
  }
}]

// ---------- The Function's storage (host and code package) and Key Vault (the GitHub token and webhook secret) ----------
resource functionStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stposture${resourceToken}'
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

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: functionStorage
  name: 'default'
}

resource packageContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'function-package'
  properties: { publicAccess: 'None' }
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-posture-${resourceToken}'
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}

// Written through Azure Resource Manager, never returned by it. The Function reads them through the private endpoint.
resource githubTokenSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(githubToken)) {
  parent: vault
  name: 'github-token'
  properties: { value: githubToken, contentType: 'text/plain' }
}

resource webhookSecretValue 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(webhookSecret)) {
  parent: vault
  name: 'github-webhook-secret'
  properties: { value: webhookSecret, contentType: 'text/plain' }
}

// ---------- The posture Function app ----------
// Logic App posture-intake calls intake with this identity's token; it has no role anywhere (function/posture/auth.py).
resource intakeIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-posture-intake-${resourceToken}'
  location: location
  tags: tags
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'plan-posture-${resourceToken}'
  location: location
  tags: tags
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: names.function
  location: location
  tags: union(tags, { 'azd-service-name': 'posture' })
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    virtualNetworkSubnetId: vnet.properties.subnets[0].id
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${functionStorage.properties.primaryEndpoints.blob}function-package'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      // One instance: intake holds a lock there, so one recommendation is handled at a time. Python handles one HTTP
      // request per instance by default; four lets a webhook delivery through while intake runs.
      scaleAndConcurrency: {
        maximumInstanceCount: 1
        instanceMemoryMB: 2048
        triggers: { http: { perInstanceConcurrency: 4 } }
      }
      runtime: { name: 'python', version: '3.12' }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      appSettings: [
        // Blob only: the Function has no queue or table triggers, and only blob has a private endpoint.
        { name: 'AzureWebJobsStorage__blobServiceUri', value: functionStorage.properties.primaryEndpoints.blob }
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
        { name: 'KEY_VAULT_URI', value: vault.properties.vaultUri }
        { name: 'AZURE_TENANT_ID', value: tenant().tenantId }
        { name: 'INTAKE_CALLER_CLIENT_ID', value: intakeIdentity.properties.clientId }
        { name: 'INTAKE_CALLER_PRINCIPAL_ID', value: intakeIdentity.properties.principalId }
        { name: 'GITHUB_REPOSITORY', value: githubRepository }
        { name: 'POSTURE_RESOURCE_GROUP_ID', value: resourceGroup().id }
        { name: 'POSTURE_STORAGE_ACCOUNT_ID', value: storageAccountId }
        { name: 'POSTURE_ASSESSMENT_KEY', value: privateLinkAssessment }
        { name: 'POSTURE_POLICY_DEFINITION', value: privateLinkPolicyDefinition }
        { name: 'POSTURE_POLICY_ASSIGNMENT', value: policyAssignmentName }
        { name: 'POSTURE_MARKER', value: marker }
        { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
        { name: 'REMEDIATION_AGENT_NAME', value: agentName }
        { name: 'POSTURE_EDITABLE_PATH', value: 'solutions/05-secure-microsoft/infra/resources.bicep' }
        { name: 'POSTURE_MODULE_PATH', value: 'app/infra/requesthub.bicep' }
        { name: 'POSTURE_INFRA_PREFIX', value: 'solutions/05-secure-microsoft/infra/' }
        { name: 'POSTURE_WHATIF_JOB_ID', value: whatifJob.id }
      ]
    }
  }
  dependsOn: [packageContainer, privateDnsGroups, privateZoneLinks]
}

// ---------- What the Function's identity may do ----------
// On this resource group: read the recommendation, the storage account, and compliance, and start a Policy evaluation.
// No write access to resources, policy assignments, or exemptions: it finds, previews, and verifies; a person deploys.
resource functionGroupRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in [roles.reader, roles.policyEnrollmentsContributor]: {
  name: guid(resourceGroup().id, functionApp.id, role)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
  }
}]

resource functionFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, functionApp.id, roles.foundryUser)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}

resource functionJobsOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: whatifJob
  name: guid(whatifJob.id, functionApp.id, roles.jobsOperator)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.jobsOperator)
  }
}

resource functionStorageOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: functionStorage
  name: guid(functionStorage.id, functionApp.id, roles.storageBlobDataOwner)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataOwner)
  }
}

resource functionSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, functionApp.id, roles.keyVaultSecretsUser)
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
  }
}

// ---------- Logic App posture-intake and Defender's workflow automation ----------
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

module intakeLogic 'logic/intake.json' = {
  name: names.intake
  params: {
    name: names.intake
    location: location
    tags: tags
    identityId: intakeIdentity.id
    connectionId: defenderConnection.id
    managedApiId: defenderConnection.properties.api.id
    functionUrl: 'https://${functionApp.properties.defaultHostName}/api/intake'
    // Entra issues no token for a managed identity as audience; Storage is one this identity has no role on.
    functionAudience: 'https://storage.azure.com/'
    resourceGroupId: resourceGroup().id
    assessmentKey: privateLinkAssessment
  }
}

output foundryProjectEndpoint string = foundryProjectEndpoint
output foundryModelDeployment string = model.name
output agentName string = agentName
output intakeWorkflowName string = names.intake
output functionAppName string = functionApp.name
output functionHost string = functionApp.properties.defaultHostName
output whatifJobName string = whatifJob.name
