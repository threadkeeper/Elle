#!/usr/bin/env pwsh
#Requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$deployScript = Join-Path $PSScriptRoot 'deploy.ps1'
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "elle-deploy-test-$([guid]::NewGuid().ToString('N'))"
$fakeBin = Join-Path $tempRoot 'bin'
$stateDir = Join-Path $tempRoot 'state'
$callLog = Join-Path $tempRoot 'az-calls.log'
$originalPath = $env:PATH
$originalStateDir = $env:FAKE_AZ_STATE_DIR
$originalCallLog = $env:FAKE_AZ_CALL_LOG
$originalPrivateImage = $env:FAKE_AZ_PRIVATE_IMAGE
$originalWisdomImage = $env:FAKE_AZ_WISDOM_IMAGE
$originalDriftAfterBuild = $env:FAKE_AZ_DRIFT_AFTER_BUILD
$originalPostUpdateImage = $env:FAKE_AZ_POST_UPDATE_IMAGE
$testsRun = 0

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Assertion failed: $Message" }
}

function Get-AzCalls {
    if (-not (Test-Path -LiteralPath $callLog)) { return @() }
    return @(Get-Content -LiteralPath $callLog)
}

function Reset-FakeAz {
    Remove-Item -LiteralPath $callLog -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stateDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $stateDir | Out-Null
    $env:FAKE_AZ_PRIVATE_IMAGE = 'registry.azurecr.io/elle:private-old'
    $env:FAKE_AZ_WISDOM_IMAGE = 'registry.azurecr.io/elle:wisdom-old'
    $env:FAKE_AZ_DRIFT_AFTER_BUILD = $null
    $env:FAKE_AZ_POST_UPDATE_IMAGE = $null
}

function Invoke-Deploy {
    param(
        [hashtable]$ExtraArguments = @{},
        [switch]$ExpectFailure
    )
    $arguments = @{
        SubscriptionId = '11111111-1111-1111-1111-111111111111'
        ResourceGroup = 'elle-test-rg'
        RegistryName = 'elleregistry'
        PrivateAppName = 'elle-private'
        WisdomAppName = 'elle-wisdom'
        ImageTag = '0123456789abcdef0123456789abcdef01234567'
    }
    foreach ($key in $ExtraArguments.Keys) { $arguments[$key] = $ExtraArguments[$key] }

    $output = [System.Collections.Generic.List[object]]::new()
    try {
        & $deployScript @arguments | ForEach-Object { $output.Add($_) }
        if ($ExpectFailure) { throw 'Deployment unexpectedly succeeded.' }
        return @($output)
    }
    catch {
        if (-not $ExpectFailure) { throw }
        $output.Add($_.Exception.Message)
        return @($output)
    }
}

function Invoke-Test {
    param([string]$Name, [scriptblock]$Body)
    & $Body
    $script:testsRun++
    Write-Output "PASS $Name"
}

try {
    New-Item -ItemType Directory -Path $fakeBin, $stateDir -Force | Out-Null
    @'
@echo off
pwsh -NoProfile -File "%~dp0fake-az.ps1" %*
exit /b %ERRORLEVEL%
'@ | Set-Content -LiteralPath (Join-Path $fakeBin 'az.cmd') -Encoding ascii
    @'
$ErrorActionPreference = 'Stop'
$arguments = @($args)
Add-Content -LiteralPath $env:FAKE_AZ_CALL_LOG -Value ($arguments -join "`t") -Encoding utf8

function Get-ArgumentValue([string]$Name) {
    $index = [Array]::IndexOf($arguments, $Name)
    if ($index -lt 0 -or $index + 1 -ge $arguments.Count) { return $null }
    return $arguments[$index + 1]
}

if ($arguments[0] -eq 'acr' -and $arguments[1] -eq 'show') {
    Write-Output 'registry.azurecr.io'
    exit 0
}
if ($arguments[0] -eq 'acr' -and $arguments[1] -eq 'build') {
    if ($env:FAKE_AZ_DRIFT_AFTER_BUILD) {
        Set-Content -LiteralPath (Join-Path $env:FAKE_AZ_STATE_DIR 'elle-private.image') `
            -Value $env:FAKE_AZ_DRIFT_AFTER_BUILD -Encoding ascii
    }
    exit 0
}
if ($arguments[0] -eq 'containerapp' -and $arguments[1] -eq 'update') {
    $app = Get-ArgumentValue '--name'
    $image = Get-ArgumentValue '--image'
    if ($env:FAKE_AZ_POST_UPDATE_IMAGE) { $image = $env:FAKE_AZ_POST_UPDATE_IMAGE }
    Set-Content -LiteralPath (Join-Path $env:FAKE_AZ_STATE_DIR "$app.image") -Value $image -Encoding ascii
    exit 0
}
if ($arguments[0] -eq 'containerapp' -and $arguments[1] -eq 'show') {
    $app = Get-ArgumentValue '--name'
    $query = Get-ArgumentValue '--query'
    if ($query -eq 'properties.configuration.ingress.fqdn') {
        Write-Output "$app.test.azurecontainerapps.io"
        exit 0
    }
    if ($query -eq 'properties.template.containers[0].image') {
        $statePath = Join-Path $env:FAKE_AZ_STATE_DIR "$app.image"
        if (Test-Path -LiteralPath $statePath) {
            Write-Output (Get-Content -LiteralPath $statePath -Raw).Trim()
        }
        elseif ($app -eq 'elle-private') { Write-Output $env:FAKE_AZ_PRIVATE_IMAGE }
        elseif ($app -eq 'elle-wisdom') { Write-Output $env:FAKE_AZ_WISDOM_IMAGE }
        else { exit 2 }
        exit 0
    }
}
exit 2
'@ | Set-Content -LiteralPath (Join-Path $fakeBin 'fake-az.ps1') -Encoding utf8

    $env:PATH = "$fakeBin$([System.IO.Path]::PathSeparator)$originalPath"
    $env:FAKE_AZ_STATE_DIR = $stateDir
    $env:FAKE_AZ_CALL_LOG = $callLog
    function global:Invoke-WebRequest {
        param(
            [string]$Uri,
            [string]$Method,
            [switch]$SkipHttpErrorCheck,
            [int]$MaximumRedirection,
            [int]$TimeoutSec
        )
        $status = if ($Uri.EndsWith('/healthz')) { 200 } else { 401 }
        return [pscustomobject]@{ StatusCode = $status }
    }

    Invoke-Test 'default Both updates and verifies both apps' {
        Reset-FakeAz
        $output = Invoke-Deploy
        $calls = Get-AzCalls
        Assert-True (@($calls | Where-Object { $_ -match '^containerapp\s+update' }).Count -eq 2) 'Both should update two apps.'
        Assert-True (@($calls | Where-Object { $_ -match 'properties\.configuration\.ingress\.fqdn' }).Count -eq 2) 'Both should read two endpoints.'
        Assert-True (($output -join "`n") -match 'endpoint\[Private\]=https://elle-private\.test\.azurecontainerapps\.io/mcp') 'Private endpoint evidence is missing.'
        Assert-True (($output -join "`n") -match 'endpoint\[Wisdom\]=https://elle-wisdom\.test\.azurecontainerapps\.io/mcp') 'Wisdom endpoint evidence is missing.'
    }

    Invoke-Test 'Private requires an expected current image' {
        Reset-FakeAz
        $failure = Invoke-Deploy -ExtraArguments @{ Target = 'Private' } -ExpectFailure
        Assert-True (($failure -join "`n") -match 'ExpectedCurrentImage') 'Missing guard should identify ExpectedCurrentImage.'
        Assert-True (@(Get-AzCalls).Count -eq 0) 'Missing guard should fail before calling az.'
    }

    Invoke-Test 'Private isolates calls and emits rollback evidence' {
        Reset-FakeAz
        $output = Invoke-Deploy -ExtraArguments @{
            Target = 'Private'
            ExpectedCurrentImage = $env:FAKE_AZ_PRIVATE_IMAGE
        }
        $calls = Get-AzCalls
        Assert-True (-not (($calls -join "`n") -match 'elle-wisdom')) 'Private must not query or update Wisdom.'
        Assert-True (@($calls | Where-Object { $_ -match '^containerapp\s+update' }).Count -eq 1) 'Private should update one app.'
        Assert-True (($output -join "`n") -match 'rollback_image\[Private\]=registry\.azurecr\.io/elle:private-old') 'Private rollback evidence is missing.'
        Assert-True (($output -join "`n") -match 'target=Private') 'Target evidence is missing.'
    }

    Invoke-Test 'image mismatch stops before build or update' {
        Reset-FakeAz
        $failure = Invoke-Deploy -ExtraArguments @{
            Target = 'Private'
            ExpectedCurrentImage = 'registry.azurecr.io/elle:not-current'
        } -ExpectFailure
        $calls = Get-AzCalls
        Assert-True (($failure -join "`n") -match 'does not match') 'Mismatch should be reported.'
        Assert-True (-not (($calls -join "`n") -match '^acr\s+build|^containerapp\s+update')) 'Mismatch must stop before build or update.'
    }

    Invoke-Test 'image drift during build stops before update' {
        Reset-FakeAz
        $expectedImage = $env:FAKE_AZ_PRIVATE_IMAGE
        $env:FAKE_AZ_DRIFT_AFTER_BUILD = 'registry.azurecr.io/elle:changed-during-build'
        $failure = Invoke-Deploy -ExtraArguments @{
            Target = 'Private'
            ExpectedCurrentImage = $expectedImage
        } -ExpectFailure
        $calls = Get-AzCalls
        Assert-True (($failure -join "`n") -match 'changed before update') 'Build-time drift should be reported.'
        Assert-True (@($calls | Where-Object { $_ -match '^acr\s+build' }).Count -eq 1) 'The drift scenario should complete the build.'
        Assert-True (@($calls | Where-Object { $_ -match '^containerapp\s+update' }).Count -eq 0) 'Build-time drift must stop before update.'
    }

    Invoke-Test 'rollback evidence precedes post-update readback failure' {
        Reset-FakeAz
        $env:FAKE_AZ_POST_UPDATE_IMAGE = 'registry.azurecr.io/elle:unexpected-after-update'
        $failure = Invoke-Deploy -ExtraArguments @{
            Target = 'Private'
            ExpectedCurrentImage = $env:FAKE_AZ_PRIVATE_IMAGE
        } -ExpectFailure
        $calls = Get-AzCalls
        Assert-True (@($calls | Where-Object { $_ -match '^containerapp\s+update' }).Count -eq 1) 'Readback failure should occur after update.'
        Assert-True ($failure[0] -eq 'rollback_target=Private') 'Rollback target evidence should precede the failure.'
        Assert-True ($failure[1] -eq 'rollback_image[Private]=registry.azurecr.io/elle:private-old') 'Prior image evidence should precede the failure.'
        Assert-True (($failure -join "`n") -match 'did not report the requested image') 'The readback failure should be reported.'
    }

    Invoke-Test 'invalid target is rejected' {
        Reset-FakeAz
        $failure = Invoke-Deploy -ExtraArguments @{ Target = 'Unknown' } -ExpectFailure
        Assert-True (($failure -join "`n") -match 'ValidateSet|Target') 'Invalid target should be rejected by parameter validation.'
        Assert-True (@(Get-AzCalls).Count -eq 0) 'Invalid target should fail before calling az.'
    }

    Write-Output "PASS $testsRun tests"
}
finally {
    Remove-Item -Path Function:\Invoke-WebRequest -Force -ErrorAction SilentlyContinue
    $env:PATH = $originalPath
    $env:FAKE_AZ_STATE_DIR = $originalStateDir
    $env:FAKE_AZ_CALL_LOG = $originalCallLog
    $env:FAKE_AZ_PRIVATE_IMAGE = $originalPrivateImage
    $env:FAKE_AZ_WISDOM_IMAGE = $originalWisdomImage
    $env:FAKE_AZ_DRIFT_AFTER_BUILD = $originalDriftAfterBuild
    $env:FAKE_AZ_POST_UPDATE_IMAGE = $originalPostUpdateImage
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}