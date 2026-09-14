#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SubscriptionId,
    [Parameter(Mandatory)][string]$ResourceGroup,
    [Parameter(Mandatory)][string]$RegistryName,
    [Parameter(Mandatory)][string]$PrivateAppName,
    [Parameter(Mandatory)][string]$WisdomAppName,
    [Parameter(Mandatory)][string]$ImageTag
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

if ($SubscriptionId -notmatch '\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\z') {
    throw 'SubscriptionId must be a GUID.'
}
if ($ResourceGroup -notmatch '\A[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,89}\z' -or $ResourceGroup.EndsWith('.')) {
    throw 'ResourceGroup has an invalid name.'
}
if ($RegistryName -notmatch '\A[a-zA-Z0-9]{5,50}\z') {
    throw 'RegistryName has an invalid name.'
}
foreach ($app in @($PrivateAppName, $WisdomAppName)) {
    if ($app -cnotmatch '\A[a-z](?:[a-z0-9-]{0,30}[a-z0-9])?\z' -or $app.Contains('--')) {
        throw 'Container app name is invalid.'
    }
}
if ($PrivateAppName -eq $WisdomAppName) {
    throw 'Private and wisdom apps must be distinct.'
}
if ($ImageTag -notmatch '\A[0-9a-fA-F]{40}\z') {
    throw 'ImageTag must be a full Git commit SHA.'
}
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI is required.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$dockerfile = Join-Path $repoRoot 'Dockerfile'
if (-not (Test-Path -LiteralPath $dockerfile -PathType Leaf)) {
    throw 'Repository Dockerfile was not found.'
}

& az acr build --subscription $SubscriptionId --registry $RegistryName `
    --image "elle:$ImageTag" --file $dockerfile --platform linux/amd64 `
    --no-logs --output none $repoRoot 2>$null
if ($LASTEXITCODE -ne 0) { throw 'Container image build failed.' }

$registryLogin = & az acr show --subscription $SubscriptionId `
    --resource-group $ResourceGroup --name $RegistryName `
    --query loginServer --output tsv 2>$null
if ($LASTEXITCODE -ne 0) { throw 'Registry lookup failed.' }
if ($registryLogin -isnot [string] -or $registryLogin -notmatch '\A[a-zA-Z0-9][a-zA-Z0-9.-]*\.azurecr\.io\z') {
    throw 'Registry returned an invalid login server.'
}
$image = "${registryLogin}/elle:$ImageTag"

foreach ($app in @($PrivateAppName, $WisdomAppName)) {
    # Only replace the image: identities, ingress, secrets and role settings are preprovisioned.
    & az containerapp update --subscription $SubscriptionId `
        --resource-group $ResourceGroup --name $app --image $image --output none 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Container app image update failed.' }
}

function Test-Endpoint {
    param(
        [string]$Uri,
        [string]$Method,
        [int]$ExpectedStatus
    )
    for ($attempt = 1; $attempt -le 10; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -Method $Method `
                -SkipHttpErrorCheck -MaximumRedirection 0 -TimeoutSec 15
            if ([int]$response.StatusCode -eq $ExpectedStatus) { return $true }
        }
        catch {
            # A revision may be starting; never print response bodies or exception details.
        }
        if ($attempt -lt 10) { Start-Sleep -Seconds 5 }
    }
    return $false
}

$verifiedUrls = @()
foreach ($app in @($PrivateAppName, $WisdomAppName)) {
    $fqdn = & az containerapp show --subscription $SubscriptionId `
        --resource-group $ResourceGroup --name $app `
        --query properties.configuration.ingress.fqdn --output tsv 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Container app endpoint lookup failed.' }
    if ($fqdn -isnot [string] -or $fqdn -notmatch '\A[a-z0-9][a-z0-9.-]*\.azurecontainerapps\.io\z') {
        throw 'Container app returned an invalid HTTPS hostname.'
    }
    $url = "https://$fqdn"
    if (-not (Test-Endpoint -Uri "$url/healthz" -Method 'GET' -ExpectedStatus 200)) {
        throw 'Container app health verification failed.'
    }
    if (-not (Test-Endpoint -Uri "$url/mcp" -Method 'POST' -ExpectedStatus 401)) {
        throw 'Container app anonymous authentication verification failed.'
    }
    $verifiedUrls += "$url/mcp"
}

foreach ($url in $verifiedUrls) { Write-Output $url }
if ($env:GITHUB_STEP_SUMMARY) {
    $verifiedUrls | Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Encoding utf8
}
