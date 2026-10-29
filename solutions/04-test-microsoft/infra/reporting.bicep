// Reports every finished load test run to GitHub, from Azure.
//
// Azure Load Testing's notification rule (created by sync_test.py, because notification rules are data-plane objects)
// sends each finished run of the test to this action group, which calls the Logic App, one run at a time. The Logic
// App, with its own managed identity:
//   - reads the run from Azure Load Testing (Load Test Reader), stops unless it is a run of this test, and waits for
//     its verdict;
//   - waits (up to about 8 minutes) until Application Insights has the run's last requests, then runs report.kql on
//     the workspace (Log Analytics Reader) to turn the run and the API's telemetry into a Markdown report and a
//     verdict, including how many requests carried the rehearsal slowdown;
//   - opens a GitHub Issue for a failing run, comments on it for the next failures, and closes it only when a run that
//     started after the Issue opened passes and the report accepts it.
// GitHub access is a fine-grained token that a person creates for this repository only, with Issues read and write, and
// sets with `azd env set GITHUB_ISSUES_TOKEN`. It is a secure parameter: GET never returns it, and the actions that use
// it have secure inputs, so it never appears in the run history. Without a token the report is built but not posted.

param environmentName string
param location string
param tags object = {}

@description('Name of the Azure Load Testing resource whose runs are reported.')
param loadTestName string

@description('Test whose runs are reported; the testId in loadtest/requesthub-journey.yaml.')
param testId string

@description('Log Analytics workspace that holds RequestHub\'s Application Insights data.')
param logAnalyticsName string

@description('GitHub repository (owner/name) where the Issues are opened. Empty: the report is built but not posted.')
param githubRepository string

@secure()
@description('Fine-grained GitHub token for this repository only, with Issues read and write. Empty: nothing is posted.')
param githubToken string

// Same token as app/infra/requesthub.bicep, so every resource in the group shares one suffix.
var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var roles = {
  loadTestReader: '3ae3fb29-0000-4ccd-bf80-542e7b26e081'
  logAnalyticsReader: '73c42c96-874c-492b-b04d-ab87d138a893'
}
var triggerName = 'When_a_test_run_ends'

resource loadTest 'Microsoft.LoadTestService/loadTests@2022-12-01' existing = {
  name: loadTestName
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsName
}

resource logicApp 'Microsoft.Logic/workflows@2019-05-01' = {
  name: 'logic-loadtest-${resourceToken}'
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    state: 'Enabled'
    definition: loadJsonContent('logicapp.json')
    parameters: {
      loadTestingEndpoint: { value: 'https://${loadTest.properties.dataPlaneURI}' }
      testId: { value: testId }
      workspaceId: { value: workspace.properties.customerId }
      resourceGroupName: { value: resourceGroup().name }
      githubRepository: { value: githubRepository }
      githubToken: { value: githubToken }
      reportQuery: { value: loadTextContent('report.kql') }
    }
  }
}

resource readRuns 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: loadTest
  name: guid(loadTest.id, logicApp.id, roles.loadTestReader)
  properties: {
    principalId: logicApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.loadTestReader)
  }
}

resource readTelemetry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: workspace
  name: guid(workspace.id, logicApp.id, roles.logAnalyticsReader)
  properties: {
    principalId: logicApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.logAnalyticsReader)
  }
}

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-loadtest-${resourceToken}'
  location: 'Global'
  tags: tags
  properties: {
    groupShortName: 'loadtest'
    enabled: true
    logicAppReceivers: [
      {
        name: 'report-to-github'
        resourceId: logicApp.id
        callbackUrl: listCallbackUrl('${logicApp.id}/triggers/${triggerName}', '2019-05-01').value
        useCommonAlertSchema: false
      }
    ]
  }
}

output logicAppName string = logicApp.name
output actionGroupId string = actionGroup.id
