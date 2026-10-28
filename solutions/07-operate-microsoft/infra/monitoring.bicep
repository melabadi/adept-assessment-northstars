// Azure Monitor assets for the notification worker: the backlog alert that Azure SRE Agent picks up, and a workbook
// that shows the backlog, the delivery rate, and the worker's configuration changes side by side.
param location string = resourceGroup().location

@description('RequestHub Application Insights component (from app/infra/requesthub.bicep).')
param appInsightsName string

@description('RequestHub Log Analytics workspace (from app/infra/requesthub.bicep).')
param logAnalyticsName string

@description('Name of the notification worker container app. Named in the alert so responders know where to look.')
param workerAppName string

@description('The alert fires when the oldest pending notification is older than this, in seconds.')
param backlogAgeThresholdSeconds int

param tags object = {}

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsName
}

// The worker publishes requesthub.notifications.oldest_pending_age_seconds (an OpenTelemetry gauge) after each batch.
// Application Insights stores OpenTelemetry metrics in the metrics store too (namespace azure.applicationinsights), so a
// metric alert evaluates it every minute and resolves three healthy minutes after the backlog drains.
var alertName = 'RequestHub notification backlog'

resource backlogAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: alertName
  location: 'global'
  tags: tags
  properties: {
    description: 'Notifications are waiting more than ${backlogAgeThresholdSeconds} seconds for the RequestHub notification worker (container app ${workerAppName}). Requesters and reviewers receive submission, comment, and decision notifications late. Signal: the worker gauge requesthub.notifications.oldest_pending_age_seconds in Application Insights. Runbook: requesthub-worker-runbook in the SRE Agent knowledge base.'
    severity: 2
    enabled: true
    scopes: [appInsights.id]
    evaluationFrequency: 'PT1M'
    windowSize: 'PT1M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          criterionType: 'StaticThresholdCriterion'
          name: 'OldestPendingNotificationAge'
          metricNamespace: 'azure.applicationinsights'
          metricName: 'requesthub.notifications.oldest_pending_age_seconds'
          operator: 'GreaterThan'
          threshold: backlogAgeThresholdSeconds
          timeAggregation: 'Maximum'
          // The metric exists only after the worker first reports it, which is after this deploys.
          skipMetricValidation: true
        }
      ]
    }
    autoMitigate: true
    actions: []
  }
}

var workbookContent = replace(replace(replace(replace(loadTextContent('workbook.json'),
  '__APP_INSIGHTS_ID__', toLower(appInsights.id)),
  '__LOG_ANALYTICS_ID__', toLower(logAnalytics.id)),
  '__WORKER_APP_NAME__', workerAppName),
  '__THRESHOLD__', string(backlogAgeThresholdSeconds))

resource workbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: guid(resourceGroup().id, 'requesthub-notification-worker')
  location: location
  tags: tags
  kind: 'shared'
  properties: {
    displayName: 'RequestHub notification worker'
    category: 'workbook'
    sourceId: toLower(appInsights.id)
    serializedData: workbookContent
  }
}

output alertName string = backlogAlert.name
output alertId string = backlogAlert.id
output workbookId string = workbook.id
