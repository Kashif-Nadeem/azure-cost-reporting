targetScope = 'managementGroup'

@description('Principal ID of the reporting Function managed identity.')
param principalId string


var billingReaderRoleId = 'fa23ad8b-c56e-40d8-ac0c-ce449e1d2c64'
var costManagementReaderRoleId = '72fafb9e-0641-4937-9268-a91bfd8191a3'


resource billingReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(
    managementGroup().id,
    principalId,
    billingReaderRoleId
  )

  properties: {
    roleDefinitionId: tenantResourceId(
      'Microsoft.Authorization/roleDefinitions',
      billingReaderRoleId
    )
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}


resource costManagementReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(
    managementGroup().id,
    principalId,
    costManagementReaderRoleId
  )

  properties: {
    roleDefinitionId: tenantResourceId(
      'Microsoft.Authorization/roleDefinitions',
      costManagementReaderRoleId
    )
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
