#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$LocalMcpUrl = '',
    [string]$TunnelId = '',
    [ValidatePattern('^[A-Za-z0-9._-]{1,64}$')]
    [string]$Profile = 'multi-agent-memory',
    [string]$TunnelClientPath = '',
    [string]$PublicMcpUrl = '',
    [string]$OAuthIssuerUrl = '',
    [switch]$Status,
    [switch]$Configure,
    [switch]$Run
)

$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$resolvedRoot = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $ProjectRoot -ErrorAction Stop).Path)
if (-not $LocalMcpUrl) {
    $siteUrl = [string]$env:MEMORYENDPOINTS_SITE_URL
    $LocalMcpUrl = if ($siteUrl) { $siteUrl.TrimEnd('/') + '/mcp' } else { 'https://127.0.0.1:8088/mcp' }
}
if (-not ($Status -or $Configure -or $Run)) { $Status = $true }

function Resolve-HttpsUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$ErrorCode,
        [switch]$RequireMcpPath,
        [switch]$RequireOrigin
    )
    $uri = $null
    if (-not [Uri]::TryCreate($Value, [UriKind]::Absolute, [ref]$uri)) { throw $ErrorCode }
    if ($uri.Scheme -cne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) { throw $ErrorCode }
    if ($RequireMcpPath -and $uri.AbsolutePath.TrimEnd('/') -cne '/mcp') { throw $ErrorCode }
    if ($RequireOrigin -and $uri.AbsolutePath.TrimEnd('/')) { throw $ErrorCode }
    return $uri.AbsoluteUri.TrimEnd('/')
}

function Test-JsonEndpoint {
    param([Parameter(Mandatory = $true)][string]$Url)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -Method Get -TimeoutSec 10
        $payload = $response.Content | ConvertFrom-Json
        return [ordered]@{ ok = $true; status = [int]$response.StatusCode; url = $Url; payload = $payload }
    }
    catch {
        $statusCode = $null
        if ($_.Exception.Response) {
            try { $statusCode = [int]$_.Exception.Response.StatusCode } catch { $statusCode = $null }
        }
        return [ordered]@{ ok = $false; status = $statusCode; url = $Url; error = 'endpoint_unavailable' }
    }
}

function Test-McpChallenge {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$ExpectedMetadataUrl
    )
    $requestBody = [ordered]@{
        jsonrpc = '2.0'
        id = 'setup-probe'
        method = 'initialize'
        params = [ordered]@{
            protocolVersion = '2025-11-25'
            capabilities = @{}
            clientInfo = [ordered]@{ name = 'setup-probe'; version = '1' }
        }
    } | ConvertTo-Json -Depth 6 -Compress
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -Method Post -ContentType 'application/json' -Body $requestBody -TimeoutSec 10
        return [ordered]@{ ok = $false; status = [int]$response.StatusCode; url = $Url; error = 'oauth_challenge_missing' }
    }
    catch {
        $statusCode = $null
        $challenge = ''
        if ($_.Exception.Response) {
            try { $statusCode = [int]$_.Exception.Response.StatusCode } catch { $statusCode = $null }
            try { $challenge = [string]$_.Exception.Response.Headers['WWW-Authenticate'] } catch { $challenge = '' }
        }
        $expected = 'resource_metadata="' + $ExpectedMetadataUrl + '"'
        $valid = $statusCode -eq 401 -and $challenge.Contains($expected) -and $challenge.Contains('scope="memory:read memory:write"')
        return [ordered]@{
            ok = [bool]$valid
            status = $statusCode
            url = $Url
            bearerChallengePresent = [bool]$challenge
            protectedResourceMetadataBound = [bool]($challenge -and $challenge.Contains($expected))
            requiredScopesAdvertised = [bool]($challenge -and $challenge.Contains('scope="memory:read memory:write"'))
        }
    }
}

function Get-NextAction {
    param(
        [Parameter(Mandatory = $true)][bool]$LocalMcpReady,
        [Parameter(Mandatory = $true)][bool]$TunnelClientInstalled,
        [Parameter(Mandatory = $true)][bool]$DcrSampleSupported,
        [Parameter(Mandatory = $true)][bool]$TunnelIdProvided,
        [Parameter(Mandatory = $true)][bool]$ControlPlaneApiKeyPresent
    )
    if (-not $LocalMcpReady) {
        return 'Start or restart the local Multi-Agent Memory host, then repair any failed MCP/OAuth readiness checks before configuring a tunnel.'
    }
    if (-not $TunnelClientInstalled) {
        return 'Download tunnel-client from OpenAI Platform Tunnels, then rerun with -Configure.'
    }
    if (-not $DcrSampleSupported) {
        return 'Update tunnel-client to a current official OpenAI build that includes the sample_mcp_with_dcr profile.'
    }
    if (-not $TunnelIdProvided) {
        return 'Create or select a tunnel in OpenAI Platform Tunnels, then pass -TunnelId.'
    }
    if (-not $ControlPlaneApiKeyPresent) {
        return 'Create a runtime API key with Tunnels Read + Use; the script will prompt without saving it.'
    }
    return 'Run -Configure, then keep -Run active while connecting from ChatGPT.'
}

$LocalMcpUrl = Resolve-HttpsUrl $LocalMcpUrl 'local_mcp_url_must_be_https_mcp_path' -RequireMcpPath
$localUri = [Uri]$LocalMcpUrl
$localOrigin = $localUri.GetLeftPart([UriPartial]::Authority)

if ($PublicMcpUrl -or $OAuthIssuerUrl) {
    if (-not ($PublicMcpUrl -and $OAuthIssuerUrl)) {
        throw 'public_mcp_url_and_oauth_issuer_url_required_together'
    }
    $PublicMcpUrl = Resolve-HttpsUrl $PublicMcpUrl 'public_mcp_url_must_be_https_mcp_path' -RequireMcpPath
    $OAuthIssuerUrl = Resolve-HttpsUrl $OAuthIssuerUrl 'oauth_issuer_url_must_be_https_origin' -RequireOrigin
    $configDirectory = Join-Path $resolvedRoot '.local-secrets'
    $configPath = Join-Path $configDirectory 'mcp-host.json'
    if (-not (Test-Path -LiteralPath $configDirectory -PathType Container)) {
        $null = New-Item -ItemType Directory -Path $configDirectory
    }
    $config = [ordered]@{
        schemaVersion = 'multi_agent_memory.mcp_host.v1'
        mcpPublicUrl = $PublicMcpUrl
        oauthIssuerUrl = $OAuthIssuerUrl
        valuesRedacted = $true
        rawCredentialExposed = $false
        rawPayloadExposed = $false
    }
    $temporaryPath = $configPath + '.tmp-' + [Guid]::NewGuid().ToString('N')
    try {
        $config | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
        Move-Item -LiteralPath $temporaryPath -Destination $configPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

$protectedMetadata = Test-JsonEndpoint ($localOrigin + '/.well-known/oauth-protected-resource/mcp')
$authorizationMetadata = Test-JsonEndpoint ($localOrigin + '/.well-known/oauth-authorization-server')
$setupStatus = Test-JsonEndpoint ($localOrigin + '/mcp/setup/status')
$expectedResource = if ($setupStatus.ok) { [string]$setupStatus.payload.mcpTransport } else { '' }
$expectedIssuer = if ($setupStatus.ok) { [string]$setupStatus.payload.oauthIssuer } else { '' }
$resourceMetadataExact = [bool](
    $protectedMetadata.ok -and $expectedResource -and
    [string]$protectedMetadata.payload.resource -ceq $expectedResource -and
    @($protectedMetadata.payload.authorization_servers).Count -eq 1 -and
    [string]@($protectedMetadata.payload.authorization_servers)[0] -ceq $expectedIssuer
)
$authorizationMetadataExact = [bool](
    $authorizationMetadata.ok -and $expectedIssuer -and
    [string]$authorizationMetadata.payload.issuer -ceq $expectedIssuer -and
    @($authorizationMetadata.payload.code_challenge_methods_supported) -contains 'S256' -and
    [string]$authorizationMetadata.payload.authorization_endpoint -ceq ($expectedIssuer + '/oauth/authorize') -and
    [string]$authorizationMetadata.payload.token_endpoint -ceq ($expectedIssuer + '/oauth/token') -and
    [string]$authorizationMetadata.payload.registration_endpoint -ceq ($expectedIssuer + '/oauth/register') -and
    [string]$authorizationMetadata.payload.revocation_endpoint -ceq ($expectedIssuer + '/oauth/revoke')
)
$challengeMetadataUrl = if ($setupStatus.ok) { [string]$setupStatus.payload.protectedResourceMetadata } else { $localOrigin + '/.well-known/oauth-protected-resource/mcp' }
$mcpChallenge = Test-McpChallenge $LocalMcpUrl $challengeMetadataUrl

$tunnelCommand = $null
if ($TunnelClientPath) {
    $resolvedClient = Resolve-Path -LiteralPath $TunnelClientPath -ErrorAction SilentlyContinue
    if (-not $resolvedClient -or -not (Test-Path -LiteralPath $resolvedClient.Path -PathType Leaf)) {
        throw 'tunnel_client_not_found'
    }
    $tunnelCommand = $resolvedClient.Path
}
else {
    $command = Get-Command tunnel-client.exe -ErrorAction SilentlyContinue
    if (-not $command) { $command = Get-Command tunnel-client -ErrorAction SilentlyContinue }
    if ($command) { $tunnelCommand = $command.Source }
}
$dcrSampleSupported = $false
if ($tunnelCommand) {
    & $tunnelCommand profiles samples show sample_mcp_with_dcr *> $null
    $dcrSampleSupported = $LASTEXITCODE -eq 0
}

$report = [ordered]@{
    schemaVersion = 'multi_agent_memory.chatgpt_mcp_setup.v1'
    localMcpUrl = $LocalMcpUrl
    localMcpReady = [bool]($setupStatus.ok -and $resourceMetadataExact -and $authorizationMetadataExact -and $mcpChallenge.ok)
    protectedResourceMetadataExact = $resourceMetadataExact
    authorizationServerMetadataExact = $authorizationMetadataExact
    protectedResourceMetadata = $protectedMetadata
    authorizationServerMetadata = $authorizationMetadata
    unauthenticatedMcpChallenge = $mcpChallenge
    setupStatus = $setupStatus
    tunnelClientInstalled = [bool]$tunnelCommand
    tunnelClientDcrSampleSupported = [bool]$dcrSampleSupported
    tunnelIdProvided = [bool]$TunnelId
    controlPlaneApiKeyPresent = [bool]$env:CONTROL_PLANE_API_KEY
    nextAction = Get-NextAction `
        -LocalMcpReady ([bool]($setupStatus.ok -and $resourceMetadataExact -and $authorizationMetadataExact -and $mcpChallenge.ok)) `
        -TunnelClientInstalled ([bool]$tunnelCommand) `
        -DcrSampleSupported ([bool]$dcrSampleSupported) `
        -TunnelIdProvided ([bool]$TunnelId) `
        -ControlPlaneApiKeyPresent ([bool]$env:CONTROL_PLANE_API_KEY)
    externalOAuthRequirement = 'Secure MCP Tunnel carries MCP discovery and calls, but the OAuth authorization server must still be reachable by the browser and OpenAI token exchange.'
    valuesRedacted = $true
    rawCredentialExposed = $false
    rawPayloadExposed = $false
}

if ($Status) {
    $report | ConvertTo-Json -Depth 8
    if (-not ($Configure -or $Run)) { return }
}
if (-not $report.localMcpReady) { throw 'local_mcp_server_not_ready' }
if (-not $tunnelCommand) { throw 'tunnel_client_not_found' }
if ($Configure -and -not $dcrSampleSupported) { throw 'tunnel_client_dcr_sample_not_supported' }
if (-not $TunnelId) { $TunnelId = Read-Host 'OpenAI tunnel_id' }
if ($TunnelId -notmatch '^tunnel_[0-9a-f]{32}$') { throw 'tunnel_id_invalid' }

$temporaryApiKey = $false
if (-not $env:CONTROL_PLANE_API_KEY) {
    $secureKey = Read-Host 'OpenAI runtime API key (input is hidden and is not saved)' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    try {
        $env:CONTROL_PLANE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        $temporaryApiKey = $true
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

try {
    if ($Configure) {
        & $tunnelCommand init --sample sample_mcp_with_dcr --profile $Profile --tunnel-id $TunnelId --mcp-server-url $LocalMcpUrl
        if ($LASTEXITCODE -ne 0) { throw 'tunnel_client_init_failed' }
        & $tunnelCommand doctor --profile $Profile --explain
        if ($LASTEXITCODE -ne 0) { throw 'tunnel_client_doctor_failed' }
    }
    if ($Run) {
        & $tunnelCommand run --profile $Profile
        if ($LASTEXITCODE -ne 0) { throw 'tunnel_client_run_failed' }
    }
}
finally {
    if ($temporaryApiKey) { Remove-Item Env:CONTROL_PLANE_API_KEY -ErrorAction SilentlyContinue }
}
