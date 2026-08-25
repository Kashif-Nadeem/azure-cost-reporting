@description('Azure region for the reporting workload.')
param location string = resourceGroup().location

@description('Azure Function App name.')
param functionAppName string

@description('Flex Consumption App Service plan name.')
param functionPlanName string

@description('Function runtime Storage Account name.')
param functionStorageAccountName string

@description('User-assigned managed identity name.')
param managedIdentityName string

@description('Application Insights resource name.')
param applicationInsightsName string

@description('Log Analytics workspace name.')
param logAnalyticsWorkspaceName string

@description('Existing Storage Account used to retain generated reports.')
param reportStorageAccountName string

@description('Blob container used for generated reports.')
param reportContainerName string = 'azure-invoice-reports'

@description('Deployment package container in Function runtime storage.')
param deploymentContainerName string = 'function-releases'

@description('Python runtime version.')
param pythonRuntimeVersion string = '3.14'

@description('Maximum Function scale-out instance count.')
@minValue(40)
@maxValue(1000)
param maximumInstanceCount int = 100

@description('Memory allocated to each Function instance.')
@allowed([
  2048
  4096
])
param instanceMemoryMB int = 2048

@description('NCRONTAB schedule. Azure Functions timer schedules use UTC by default.')
param monthlyReportSchedule string = '0 0 13 5 * *'

@description('Optional month override in YYYY-MM format for testing.')
param reportMonthOverride string = ''

@description('Comma-separated report recipient addresses. Configure in Azure, not source control.')
param reportRecipients string = ''

@description('Mailbox used to send reports. Configure in Azure, not source control.')
param reportSender string = ''

@description('Controls whether email delivery is enabled.')
param emailEnabled bool = false

@description('Email subject prefix.')
param reportSubjectPrefix string = 'Azure Invoice Expense Report'

@description('Azure Billing REST API version.')
param billingApiVersion string = '2024-04-01'

@description('Azure subscriptions REST API version.')
param subscriptionsApiVersion string = '2022-12-01'


// Built-in Azure role IDs.
var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
var storageTableDataContributorRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
var monitoringMetricsPublisherRoleId = '3913510d-42f4-4e42-8a64-420c390055eb'


// -----------------------------------------------------------------------------
// Monitoring
// -----------------------------------------------------------------------------

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsWorkspaceName
  location: location

  properties: {
    retentionInDays: 30

    sku: {
      name: 'PerGB2018'
    }

    features: {
      searchVersion: 1
    }
  }
}


resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: applicationInsightsName
  location: location
  kind: 'web'

  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    DisableLocalAuth: true
  }
}


// -----------------------------------------------------------------------------
// Managed identity
// -----------------------------------------------------------------------------

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
}


// -----------------------------------------------------------------------------
// Function runtime storage
// -----------------------------------------------------------------------------

resource functionStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: functionStorageAccountName
  location: location
  kind: 'StorageV2'

  sku: {
    name: 'Standard_LRS'
  }

  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'

    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }

  resource blobService 'blobServices' = {
    name: 'default'

    properties: {}

    resource deploymentContainer 'containers' = {
      name: deploymentContainerName

      properties: {
        publicAccess: 'None'
      }
    }
  }
}


// -----------------------------------------------------------------------------
// Existing storage for generated reports
// -----------------------------------------------------------------------------

resource reportStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: reportStorageAccountName
}

resource reportBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: reportStorage
  name: 'default'
}

resource reportContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: reportBlobService
  name: reportContainerName

  properties: {
    publicAccess: 'None'
  }
}


// -----------------------------------------------------------------------------
// Runtime storage RBAC
// -----------------------------------------------------------------------------

resource blobOwnerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(
    functionStorage.id,
    managedIdentity.id,
    storageBlobDataOwnerRoleId
  )
  scope: functionStorage

  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      storageBlobDataOwnerRoleId
    )
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}


resource blobContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(
    functionStorage.id,
    managedIdentity.id,
    storageBlobDataContributorRoleId
  )
  scope: functionStorage

  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      storageBlobDataContributorRoleId
    )
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}


resource queueContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(
    functionStorage.id,
    managedIdentity.id,
    storageQueueDataContributorRoleId
  )
  scope: functionStorage

  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      storageQueueDataContributorRoleId
    )
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}


resource tableContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(
    functionStorage.id,
    managedIdentity.id,
    storageTableDataContributorRoleId
  )
  scope: functionStorage

  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      storageTableDataContributorRoleId
    )
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}


// Only allow the Function to write to the report container.
resource reportBlobContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(
    reportContainer.id,
    managedIdentity.id,
    storageBlobDataContributorRoleId
  )
  scope: reportContainer

  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      storageBlobDataContributorRoleId
    )
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}


// -----------------------------------------------------------------------------
// Flex Consumption plan
// -----------------------------------------------------------------------------

resource functionPlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: functionPlanName
  location: location
  kind: 'functionapp'

  sku: {
    tier: 'FlexConsumption'
    name: 'FC1'
  }

  properties: {
    reserved: true
  }
}


// -----------------------------------------------------------------------------
// Function App
// -----------------------------------------------------------------------------

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'

  identity: {
    type: 'UserAssigned'

    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }

  properties: {
    serverFarmId: functionPlan.id
    httpsOnly: true

    siteConfig: {
      minTlsVersion: '1.2'
    }

    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${functionStorage.properties.primaryEndpoints.blob}${deploymentContainerName}'

          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: managedIdentity.id
          }
        }
      }

      scaleAndConcurrency: {
        maximumInstanceCount: maximumInstanceCount
        instanceMemoryMB: instanceMemoryMB
      }

      runtime: {
        name: 'python'
        version: pythonRuntimeVersion
      }
    }
  }

  resource appSettings 'config' = {
    name: 'appsettings'

    properties: {
      FUNCTIONS_WORKER_RUNTIME: 'python'

      AzureWebJobsStorage__accountName: functionStorage.name
      AzureWebJobsStorage__credential: 'managedidentity'
      AzureWebJobsStorage__clientId: managedIdentity.properties.clientId

      APPLICATIONINSIGHTS_CONNECTION_STRING: applicationInsights.properties.ConnectionString
      APPLICATIONINSIGHTS_AUTHENTICATION_STRING: 'ClientId=${managedIdentity.properties.clientId};Authorization=AAD'

      AZURE_CLIENT_ID: managedIdentity.properties.clientId

      MONTHLY_REPORT_SCHEDULE: monthlyReportSchedule
      REPORT_MONTH_OVERRIDE: reportMonthOverride

      REPORT_STORAGE_ACCOUNT: reportStorage.name
      REPORT_CONTAINER: reportContainer.name

      REPORT_RECIPIENTS: reportRecipients
      REPORT_SENDER: reportSender
      REPORT_SUBJECT_PREFIX: reportSubjectPrefix
      EMAIL_ENABLED: emailEnabled ? 'true' : 'false'

      BILLING_API_VERSION: billingApiVersion
      SUBSCRIPTIONS_API_VERSION: subscriptionsApiVersion
    }
  }
}


// -----------------------------------------------------------------------------
// Application Insights RBAC
// -----------------------------------------------------------------------------

resource monitoringMetricsPublisherRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(
    applicationInsights.id,
    managedIdentity.id,
    monitoringMetricsPublisherRoleId
  )
  scope: applicationInsights

  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      monitoringMetricsPublisherRoleId
    )
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}


output functionAppName string = functionApp.name
output functionAppResourceId string = functionApp.id

output managedIdentityName string = managedIdentity.name
output managedIdentityPrincipalId string = managedIdentity.properties.principalId
output managedIdentityClientId string = managedIdentity.properties.clientId

output functionStorageAccountName string = functionStorage.name
output reportContainerName string = reportContainer.name
