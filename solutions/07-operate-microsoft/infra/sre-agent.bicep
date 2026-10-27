// Azure SRE Agent for this solution. It watches this resource group only, receives Azure Monitor alerts from it, and
// can read (not change) its resources and telemetry. Write actions need an SRE Agent Administrator's approval and run
// with that person's own Azure permissions (on-behalf-of). configure_sre_agent.py adds the custom agent, skills,
// runbook, response plan, and tool policy after this deploys.
@description('Name of the SRE Agent. Unique in the subscription: letters, digits, and hyphens, 2 to 32 characters.')
@minLength(2)
@maxLength(32)
param agentName string

param location string = resourceGroup().location

@description('RequestHub Application Insights component the agent investigates.')
param workloadAppInsightsName string

@description('RequestHub Log Analytics workspace the agent investigates. The agent\'s own telemetry goes there too, in a separate component.')
param logAnalyticsName string

@allowed(['MicrosoftFoundry', 'Anthropic'])
param modelProvider string = 'MicrosoftFoundry'

@minValue(500)
@description('Monthly cap on active-flow Azure Agent Units (chats and investigations). The always-on charge is separate.')
param monthlyAgentUnitLimit int = 1000

@description('Object id of the presenter. Receives the SRE Agent Administrator role: chat, approve actions, configure the agent.')
param presenterPrincipalId string

@allowed(['User', 'ServicePrincipal'])
param presenterPrincipalType string = 'User'

@description('Principal id of the GitHub Actions identity that applies the agent configuration from main. Empty skips its roles.')
param automationPrincipalId string = ''

param tags object = {}

var token = toLower(uniqueString(resourceGroup().id, agentName))
var roles = {
  reader: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
  monitoringReader: '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
  logAnalyticsReader: '73c42c96-874c-492b-b04d-ab87d138a893'
  sreAgentAdministrator: 'e79298df-d852-4c6d-84f9-5d13249d1e55'
  sreAgentAuthor: 'eb64ab4c-23eb-4f63-a9c2-27da365f04e7'
  sreAgentStandardUser: '2d84a65a-63b2-4343-bbb6-31105d857bc1'
}
// Read-only access to this resource group: resources, metrics, alerts, and logs. Nothing that can change them.
var readRoles = [roles.reader, roles.monitoringReader, roles.logAnalyticsReader]
// Enough to update custom agents, skills, response plans, and knowledge. Neither role can approve the agent's actions
// or change its global tool policy.
var automationRoles = empty(automationPrincipalId) ? [] : [roles.sreAgentAuthor, roles.sreAgentStandardUser]

resource workloadAppInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: workloadAppInsightsName
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsName
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-sre-${token}'
  location: location
  tags: tags
}

resource identityRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in readRoles: {
  name: guid(resourceGroup().id, identity.id, roleId)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
  }
}]

// The agent's own telemetry (its runs and tool calls), kept apart from RequestHub's.
resource agentInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-sre-${token}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

resource agent 'Microsoft.App/agents@2026-01-01' = {
  name: agentName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    // The resource groups the agent manages: alerts from them become incidents, and its identity can read them.
    knowledgeGraphConfiguration: {
      identity: identity.id
      managedResources: [resourceGroup().id]
    }
    // Low (Reader) access, Review mode: the agent proposes write actions and an administrator approves each one.
    actionConfiguration: {
      accessLevel: 'Low'
      identity: identity.id
      mode: 'Review'
    }
    incidentManagementConfiguration: {
      type: 'AzMonitor'
      connectionName: 'azmonitor'
    }
    logConfiguration: {
      applicationInsightsConfiguration: {
        appId: agentInsights.properties.AppId
        connectionString: agentInsights.properties.ConnectionString
      }
    }
    upgradeChannel: 'Stable'
    #disable-next-line BCP037
    monthlyAgentUnitLimit: monthlyAgentUnitLimit
    defaultModel: {
      provider: modelProvider
      name: 'Automatic'
    }
  }
  dependsOn: [identityRoles]
}

// Telemetry connectors query with the agent's system-assigned identity, so it gets the same read-only roles.
resource systemIdentityRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in readRoles: {
  name: guid(resourceGroup().id, agent.id, 'system', roleId)
  properties: {
    principalId: agent.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
  }
}]

resource presenterAdministrator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: agent
  name: guid(agent.id, presenterPrincipalId, roles.sreAgentAdministrator)
  properties: {
    principalId: presenterPrincipalId
    principalType: presenterPrincipalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.sreAgentAdministrator)
  }
}

resource automationAgentRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in automationRoles: {
  scope: agent
  name: guid(agent.id, automationPrincipalId, roleId)
  properties: {
    principalId: automationPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
  }
}]

// Connectors are only exposed in the preview API version.
#disable-next-line BCP081
resource appInsightsConnector 'Microsoft.App/agents/connectors@2025-05-01-preview' = {
  parent: agent
  name: 'app-insights'
  properties: {
    dataConnectorType: 'AppInsights'
    dataSource: workloadAppInsights.id
    extendedProperties: {
      armResourceId: workloadAppInsights.id
      resource: { name: workloadAppInsights.name }
      appId: workloadAppInsights.properties.AppId
    }
    identity: 'system'
  }
  dependsOn: [systemIdentityRoles]
}

#disable-next-line BCP081
resource logAnalyticsConnector 'Microsoft.App/agents/connectors@2025-05-01-preview' = {
  parent: agent
  name: 'log-analytics'
  properties: {
    dataConnectorType: 'LogAnalytics'
    dataSource: logAnalytics.id
    extendedProperties: {
      armResourceId: logAnalytics.id
      resource: { name: logAnalytics.name }
    }
    identity: 'system'
  }
  dependsOn: [appInsightsConnector]
}

output agentName string = agent.name
output agentId string = agent.id
output portalUrl string = 'https://sre.azure.com/agents${agent.id}'
