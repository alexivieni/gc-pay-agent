<#
Creates everything the agent needs in Azure, then writes .env for the Python scripts:
resource group, Foundry resource, Foundry project, chat model deployment, and your
Foundry User role on the project. Safe to re-run: anything that exists is reused.

Run from the project folder after `az login`:

    .\setup-azure.ps1                                   # defaults: eastus, gpt-5-mini
    .\setup-azure.ps1 -ListModels                       # see which models the region offers
    .\setup-azure.ps1 -ModelName <name> -ModelVersion <version>
    .\setup-azure.ps1 -Capacity 100                     # raise the model's rate limit

Delete everything when you're done (stops all charges):

    az group delete -n rg-gc-pay-agent --yes --no-wait
#>

param(
    [string]$Location = "eastus",
    [string]$ResourceGroup = "rg-gc-pay-agent",
    [string]$ProjectName = "gc-pay-agent",
    [string]$ModelName = "gpt-5-mini",
    [string]$ModelVersion = "2025-08-07",
    [int]$Capacity = 50,          # thousands of tokens per minute the model accepts
    [switch]$ListModels
)

# Foundry User (formerly Azure AI User). Microsoft recommends the ID over the name.
$FoundryUserRole = "53ca6127-db72-4b80-b1b0-d745d6d5456d"

function Assert-Ok([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "Failed: $Step. See the error above." }
}

function Test-Exists([string[]]$AzArgs) {
    & az @AzArgs -o none 2>$null
    return ($LASTEXITCODE -eq 0)
}

if ($ListModels) {
    Write-Host "OpenAI models offered in $Location (name, version):"
    az cognitiveservices model list -l $Location -o json | ConvertFrom-Json |
        Where-Object { $_.model.format -eq "OpenAI" } |
        ForEach-Object { "{0}  {1}" -f $_.model.name, $_.model.version } |
        Sort-Object -Unique
    exit 0
}

Write-Host "Checking your Azure sign-in..."
$sub = az account show --query id -o tsv
Assert-Ok "read your subscription (run 'az login' first)"
$me = az ad signed-in-user show --query id -o tsv
Assert-Ok "look up your user"

# Stable, globally unique name for this subscription, so re-runs find the same resource
$AccountName = "gcpay-$($sub.Substring(0, 8))"

Write-Host "1/5 Resource group $ResourceGroup ($Location)"
az group create -n $ResourceGroup -l $Location -o none
Assert-Ok "create resource group"

Write-Host "2/5 Foundry resource $AccountName"
if (Test-Exists @("cognitiveservices", "account", "show", "-n", $AccountName, "-g", $ResourceGroup)) {
    Write-Host "    already exists"
} else {
    az cognitiveservices account create -n $AccountName -g $ResourceGroup -l $Location `
        --kind AIServices --sku S0 --custom-domain $AccountName `
        --assign-identity --allow-project-management true --yes -o none
    Assert-Ok "create Foundry resource"
}

Write-Host "3/5 Project $ProjectName"
if (Test-Exists @("cognitiveservices", "account", "project", "show", "--name", $AccountName, "-g", $ResourceGroup, "--project-name", $ProjectName)) {
    Write-Host "    already exists"
} else {
    az cognitiveservices account project create --name $AccountName -g $ResourceGroup `
        --project-name $ProjectName --location $Location -o none
    Assert-Ok "create project"
}

Write-Host "4/5 Model deployment $ModelName ($ModelVersion), capacity $Capacity (= $($Capacity)K tokens/minute)"
$deployment = $null
if (Test-Exists @("cognitiveservices", "account", "deployment", "show", "--name", $AccountName, "-g", $ResourceGroup, "--deployment-name", $ModelName)) {
    $deployment = az cognitiveservices account deployment show --name $AccountName -g $ResourceGroup `
        --deployment-name $ModelName -o json | ConvertFrom-Json
}
if ($deployment -and [int]$deployment.sku.capacity -eq $Capacity) {
    Write-Host "    already exists"
} else {
    if ($deployment) { Write-Host "    changing capacity from $($deployment.sku.capacity) to $Capacity" }
    az cognitiveservices account deployment create --name $AccountName -g $ResourceGroup `
        --deployment-name $ModelName --model-name $ModelName --model-version $ModelVersion `
        --model-format OpenAI --sku-name GlobalStandard --sku-capacity $Capacity -o none
    Assert-Ok "deploy model (quota error: try a lower -Capacity; model not supported: run .\setup-azure.ps1 -ListModels)"
}

$project = az cognitiveservices account project show --name $AccountName -g $ResourceGroup `
    --project-name $ProjectName -o json | ConvertFrom-Json
Assert-Ok "read project details"
$endpoint = $project.properties.endpoints.'AI Foundry API'
if (-not $endpoint) { throw "Couldn't find the project endpoint in the project details." }

Write-Host "5/5 Foundry User role for you on the project"
# Filter in PowerShell rather than with an az --query, which Windows can mangle
$assignments = az role assignment list --scope $project.id --include-inherited -o json | ConvertFrom-Json
Assert-Ok "check role assignments"
$hasRole = @($assignments | Where-Object {
    $_.principalId -eq $me -and $_.roleDefinitionId -like "*$FoundryUserRole"
}).Count -gt 0
if ($hasRole) {
    Write-Host "    already assigned"
} else {
    az role assignment create --assignee-object-id $me --assignee-principal-type User `
        --role $FoundryUserRole --scope $project.id -o none
    Assert-Ok "assign Foundry User role"
}

# Written without a byte-order mark so Python reads the first setting correctly
$envText = "PROJECT_ENDPOINT=$endpoint`nMODEL_DEPLOYMENT=$ModelName`nAGENT_NAME=gc-pay-agent`n"
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot ".env"), $envText)

Write-Host ""
Write-Host "Done. .env written with your project endpoint:"
Write-Host "    $endpoint"
Write-Host "Role assignments can take a minute or two to apply. Next:"
Write-Host "    python get_agreements.py"
Write-Host "    python create_agent.py"
