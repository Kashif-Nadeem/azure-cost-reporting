@description('Azure region for the Key Vault.')
param location string = resourceGroup().location

@description('Key Vault name.')
param keyVaultName string

@description('Principal ID that requires read-only secret access.')
param managedIdentityPrincipalId string

@description('Soft-delete retention period in days.')
@minValue(7)
@maxValue(90)
param softDeleteRetentionInDays int = 90

@description('Enable purge protection for production secrets.')
param enablePurgeProtection bool = true


var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'


resource keyVault 'Microsoft.KeyVault/vaults@2026-02-01' = {
  name: keyVaultName
  location: location

  properties: {
    tenantId: tenant().tenantId

    sku: {
      family: 'A'
      name: 'standard'
    }

    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: softDeleteRetentionInDays
    enablePurgeProtection: enablePurgeProtection

    publicNetworkAccess: 'Enabled'

    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }
}


resource managedIdentitySecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(
    keyVault.id,
    managedIdentityPrincipalId,
    keyVaultSecretsUserRoleId
  )

  scope: keyVault

  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      keyVaultSecretsUserRoleId
    )

    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}


output keyVaultName string = keyVault.name
output keyVaultId string = keyVault.id
output vaultUri string = keyVault.properties.vaultUri
