#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SubscriptionId,
    [Parameter(Mandatory)][string]$ResourceGroup,
    [Parameter(Mandatory)][string]$RegistryName,
    [Parameter(Mandatory)][string]$PrivateAppName,
    [Parameter(Mandatory)][string]$WisdomAppName,
    [Parameter(Mandatory)][string]$ImageTag,
    [ValidateSet('Both', 'Private', 'Wisdom')][string]$Target = 'Both',
    [string]$ExpectedCurrentImage
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
if ($Target -ne 'Both' -and [string]::IsNullOrWhiteSpace($ExpectedCurrentImage)) {
    throw 'ExpectedCurrentImage is required for a single-service target.'
}
if ($Target -ne 'Both' -and $ExpectedCurrentImage -cnotmatch '\A[a-zA-Z0-9][a-zA-Z0-9._:/@-]{0,1023}\z') {
    throw 'ExpectedCurrentImage has an invalid image reference.'
}
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI is required.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$dockerfile = Join-Path $repoRoot 'Dockerfile'
if (-not (Test-Path -LiteralPath $dockerfile -PathType Leaf)) {
    throw 'Repository Dockerfile was not found.'
}

$selectedApps = @(switch ($Target) {
    'Both' {
        [pscustomobject]@{ Role = 'Private'; Name = $PrivateAppName }
        [pscustomobject]@{ Role = 'Wisdom'; Name = $WisdomAppName }
    }
    'Private' { [pscustomobject]@{ Role = 'Private'; Name = $PrivateAppName } }
    'Wisdom' { [pscustomobject]@{ Role = 'Wisdom'; Name = $WisdomAppName } }
})

function Get-CurrentImage {
    param([string]$AppName)

    $currentImage = & az containerapp show --subscription $SubscriptionId `
        --resource-group $ResourceGroup --name $AppName `
        --query 'properties.template.containers[0].image' --output tsv 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Container app image lookup failed.' }
    if ($currentImage -isnot [string] -or
        $currentImage -cnotmatch '\A[a-zA-Z0-9][a-zA-Z0-9._:/@-]{0,1023}\z') {
        throw 'Container app returned an invalid image reference.'
    }
    return $currentImage
}

$rollbackImages = @{}
foreach ($app in $selectedApps) {
    $rollbackImages[$app.Role] = Get-CurrentImage -AppName $app.Name
}
if ($Target -ne 'Both' -and $rollbackImages[$Target] -cne $ExpectedCurrentImage) {
    throw "The $Target app current image does not match ExpectedCurrentImage."
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

foreach ($app in $selectedApps) {
    $currentImage = Get-CurrentImage -AppName $app.Name
    if ($Target -ne 'Both' -and $currentImage -cne $ExpectedCurrentImage) {
        throw "The $Target app current image changed before update and does not match ExpectedCurrentImage."
    }
    $rollbackImages[$app.Role] = $currentImage
    $rollbackEvidence = @(
        "rollback_target=$($app.Role)"
        "rollback_image[$($app.Role)]=$currentImage"
    )
    $rollbackEvidence | Write-Output
    if ($env:GITHUB_STEP_SUMMARY) {
        $rollbackEvidence | Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Encoding utf8
    }

    # Only replace the image: identities, ingress, secrets and role settings are preprovisioned.
    & az containerapp update --subscription $SubscriptionId `
        --resource-group $ResourceGroup --name $app.Name --image $image --output none 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Container app image update failed.' }
    $deployedImage = Get-CurrentImage -AppName $app.Name
    if ($deployedImage -cne $image) {
        throw "The $($app.Role) app did not report the requested image after update."
    }
}

function Test-Endpoint {
    param(
        [string]$Uri,
        [string]$Method,
        [int]$ExpectedStatus,
        [string]$ContentType,
        [string]$Body
    )
    for ($attempt = 1; $attempt -le 10; $attempt++) {
        try {
            $requestArguments = @{
                Uri = $Uri
                Method = $Method
                SkipHttpErrorCheck = $true
                MaximumRedirection = 0
                TimeoutSec = 15
            }
            if ($ContentType) { $requestArguments.ContentType = $ContentType }
            if ($Body) { $requestArguments.Body = $Body }
            $response = Invoke-WebRequest @requestArguments
            if ([int]$response.StatusCode -eq $ExpectedStatus) { return $true }
        }
        catch {
            # A revision may be starting; never print response bodies or exception details.
        }
        if ($attempt -lt 10) { Start-Sleep -Seconds 5 }
    }
    return $false
}

$verifiedEndpoints = @{}
foreach ($app in $selectedApps) {
    $fqdn = & az containerapp show --subscription $SubscriptionId `
        --resource-group $ResourceGroup --name $app.Name `
        --query properties.configuration.ingress.fqdn --output tsv 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Container app endpoint lookup failed.' }
    if ($fqdn -isnot [string] -or $fqdn -notmatch '\A[a-z0-9][a-z0-9.-]*\.azurecontainerapps\.io\z') {
        throw 'Container app returned an invalid HTTPS hostname.'
    }
    $url = "https://$fqdn"
    if (-not (Test-Endpoint -Uri "$url/healthz" -Method 'GET' -ExpectedStatus 200)) {
        throw 'Container app health verification failed.'
    }
    if ($app.Role -eq 'Private' -and
        -not (Test-Endpoint -Uri "$url/bridge/elle_context" -Method 'POST' -ExpectedStatus 401 `
            -ContentType 'application/json' -Body '{}')) {
        throw 'Private bridge authentication verification failed.'
    }
    if ($app.Role -eq 'Private') {
        $verifiedEndpoints[$app.Role] = "$url/bridge/elle_context"
    }
    else {
        $verifiedEndpoints[$app.Role] = "$url/healthz"
    }
}

$evidence = @("target=$Target", "new_image=$image")
foreach ($app in $selectedApps) {
    $evidence += "endpoint[$($app.Role)]=$($verifiedEndpoints[$app.Role])"
}
$evidence | Write-Output
if ($env:GITHUB_STEP_SUMMARY) {
    $evidence | Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Encoding utf8
}
