<#
Deploys infra/main.bicep, the declarative alternative to setup-azure.ps1, then writes .env.
Both approaches create the same resources with the same names, so you can use either one.

Run from the project folder after `az login`:

    .\infra\deploy.ps1
    .\infra\deploy.ps1 -Capacity 100            # raise the model's rate limit

Deploying again is safe: Azure compares the template with what exists and changes only the
differences.
#>

param(
    [string]$ResourceGroup = "rg-gc-pay-agent",
    [string]$Location = "eastus",
    [string]$ProjectName = "gc-pay-agent",
    [int]$Capacity = 50
)

# Foundry User (formerly Azure AI User)
$FoundryUserRole = "53ca6127-db72-4b80-b1b0-d745d6d5456d"

function Assert-Ok([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "Failed: $Step. See the error above." }
}

Write-Host "Checking your Azure sign-in..."
$sub = az account show --query id -o tsv
Assert-Ok "read your subscription (run 'az login' first)"
$me = az ad signed-in-user show --query id -o tsv
Assert-Ok "look up your user"

Write-Host "Resource group $ResourceGroup ($Location)"
az group create -n $ResourceGroup -l $Location -o none
Assert-Ok "create resource group"

# Skip the role assignment if you already hold the role (for example, from setup-azure.ps1).
# Declaring a second, identical assignment would fail.
$account = "gcpay-$($sub.Substring(0, 8))"
$scope = "/subscriptions/$sub/resourceGroups/$ResourceGroup/providers/Microsoft.CognitiveServices/accounts/$account/projects/$ProjectName"
$assignments = az role assignment list --scope $scope --include-inherited -o json 2>$null | ConvertFrom-Json
$hasRole = @($assignments | Where-Object {
    $_.principalId -eq $me -and $_.roleDefinitionId -like "*$FoundryUserRole"
}).Count -gt 0
$assignRole = if ($hasRole) { "false" } else { "true" }

Write-Host "Deploying infra/main.bicep (a few minutes on the first run)..."
$outputs = az deployment group create -g $ResourceGroup -n gc-pay-agent `
    -f (Join-Path $PSScriptRoot "main.bicep") `
    -p principalId=$me assignRole=$assignRole projectName=$ProjectName capacity=$Capacity `
    --query properties.outputs -o json | ConvertFrom-Json
Assert-Ok "deploy main.bicep"

# Written without a byte-order mark so Python reads the first setting correctly
$envText = "PROJECT_ENDPOINT=$($outputs.projectEndpoint.value)`nMODEL_DEPLOYMENT=$($outputs.modelDeployment.value)`nAGENT_NAME=gc-pay-agent`n"
[System.IO.File]::WriteAllText((Join-Path (Split-Path $PSScriptRoot -Parent) ".env"), $envText)

Write-Host ""
Write-Host "Done. .env written with your project endpoint:"
Write-Host "    $($outputs.projectEndpoint.value)"
Write-Host "Role assignments can take a minute or two to apply. Next:"
Write-Host "    python get_agreements.py"
Write-Host "    python create_agent.py"
