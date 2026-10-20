// Declarative version of setup-azure.ps1: the same Azure resources, described as code.
// Deploy into an existing resource group with infra/deploy.ps1, which also writes .env.
//
// Creates: Foundry resource, Foundry project, model deployment, and the Foundry User role
// for one principal (a person or a service principal) on the project.
// Names match setup-azure.ps1, so either approach manages the same resources.

targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Foundry resource name. Derived from the subscription ID by default, as in setup-azure.ps1.')
param accountName string = 'gcpay-${substring(subscription().subscriptionId, 0, 8)}'

@description('Foundry project name.')
param projectName string = 'gc-pay-agent'

@description('Model to deploy. The deployment uses the same name.')
param modelName string = 'gpt-5-mini'

@description('Model version.')
param modelVersion string = '2025-08-07'

@description('Deployment capacity, in thousands of tokens per minute.')
@minValue(1)
param capacity int = 50

@description('Object ID of the person or service principal that will create and call agents.')
param principalId string

@description('Type of that principal.')
@allowed([
  'User'
  'ServicePrincipal'
  'Group'
])
param principalType string = 'User'

@description('Set to false if the principal already holds the Foundry User role on the project.')
param assignRole bool = true

// Foundry User (formerly Azure AI User): data-plane access to create and invoke agents.
var foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: accountName
    allowProjectManagement: true
    // Keys are switched off: every caller must sign in with Microsoft Entra ID.
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: modelName
  sku: {
    name: 'GlobalStandard'
    capacity: capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

resource foundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRole) {
  scope: project
  name: guid(project.id, principalId, foundryUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
    principalId: principalId
    principalType: principalType
  }
}

@description('Project endpoint for PROJECT_ENDPOINT in .env.')
output projectEndpoint string = 'https://${accountName}.services.ai.azure.com/api/projects/${projectName}'

@description('Model deployment name for MODEL_DEPLOYMENT in .env.')
output modelDeployment string = modelDeployment.name
