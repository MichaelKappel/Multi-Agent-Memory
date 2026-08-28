#requires -Version 5.1
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$ProjectRoot = '',
    [string]$TaskName = 'Multi-Agent-Memory LAN Host',
    [string]$PythonPath = '',
    [string]$BindHost = '0.0.0.0',
    [Parameter(Mandatory = $true)]
    [string]$AdvertiseHost,
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8088,
    [ValidateRange(1, 65535)]
    [int]$DocsPort = 8090,
    [Parameter(Mandatory = $true)]
    [string]$AllowedNetwork,
    [string]$TlsCertificatePath = '',
    [string]$TlsKeyPath = '',
    [string]$TlsCaPath = '',
    [ValidateRange(5, 300)]
    [int]$StartupTimeoutSeconds = 45,
    [switch]$PlanOnly,
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }

function Resolve-RequiredFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ErrorCode
    )
    if ($Path.Contains('"')) { throw "${ErrorCode}_invalid_quote" }
    $resolved = Resolve-Path -LiteralPath $Path -ErrorAction SilentlyContinue
    if (-not $resolved -or -not (Test-Path -LiteralPath $resolved.Path -PathType Leaf)) {
        throw $ErrorCode
    }
    return [IO.Path]::GetFullPath($resolved.Path)
}

function Quote-WindowsArgument {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ($Value.Contains('"') -or $Value.Contains("`r") -or $Value.Contains("`n")) {
        throw 'task_argument_contains_forbidden_character'
    }
    return '"' + $Value + '"'
}

function Resolve-PythonExecutables {
    param([string]$RequestedPath)
    $taskPython = $RequestedPath
    if (-not $taskPython) {
        $command = Get-Command pythonw.exe -ErrorAction SilentlyContinue
        if ($command) {
            $taskPython = $command.Source
        }
        else {
            $console = Get-Command python.exe -ErrorAction SilentlyContinue
            if (-not $console) { throw 'python_executable_not_found' }
            $candidate = Join-Path (Split-Path -Parent $console.Source) 'pythonw.exe'
            $taskPython = if (Test-Path -LiteralPath $candidate -PathType Leaf) { $candidate } else { $console.Source }
        }
    }
    $taskPython = Resolve-RequiredFile $taskPython 'python_executable_not_found'
    $consolePython = Join-Path (Split-Path -Parent $taskPython) 'python.exe'
    if (-not (Test-Path -LiteralPath $consolePython -PathType Leaf)) {
        $consolePython = $taskPython
    }
    return @{
        Task = [IO.Path]::GetFullPath($taskPython)
        Console = [IO.Path]::GetFullPath($consolePython)
    }
}

function Test-SameText {
    param([object]$Left, [object]$Right)
    return [string]::Equals([string]$Left, [string]$Right, [StringComparison]::OrdinalIgnoreCase)
}

function Resolve-AccountSid {
    param([object]$AccountName)
    try {
        $account = [Security.Principal.NTAccount]::new([string]$AccountName)
        return $account.Translate([Security.Principal.SecurityIdentifier]).Value
    }
    catch {
        return $null
    }
}

function Test-SameAccount {
    param([object]$Left, [object]$Right)
    $leftSid = Resolve-AccountSid $Left
    $rightSid = Resolve-AccountSid $Right
    if ($leftSid -and $rightSid) {
        return [string]::Equals($leftSid, $rightSid, [StringComparison]::OrdinalIgnoreCase)
    }
    return Test-SameText $Left $Right
}

$resolvedRoot = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $ProjectRoot -ErrorAction Stop).Path)
$launcher = Resolve-RequiredFile (Join-Path $resolvedRoot 'scripts\serve_lan.py') 'tracked_launcher_not_found'
if (-not (Test-SameText (Split-Path -Parent (Split-Path -Parent $launcher)) $resolvedRoot)) {
    throw 'tracked_launcher_outside_project_root'
}
if ($ApiPort -eq $DocsPort) { throw 'listener_ports_must_differ' }

$parsedBind = $null
$parsedAdvertise = $null
if (-not [Net.IPAddress]::TryParse($BindHost, [ref]$parsedBind)) { throw 'bind_host_must_be_ip_literal' }
if (-not [Net.IPAddress]::TryParse($AdvertiseHost, [ref]$parsedAdvertise)) { throw 'advertise_host_must_be_ip_literal' }
if (
    $parsedBind.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
    $parsedAdvertise.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork
) { throw 'lan_host_ipv4_required' }
$networkParts = $AllowedNetwork.Split('/')
$parsedNetworkAddress = $null
$parsedPrefix = 0
if (
    $networkParts.Count -ne 2 -or
    -not [Net.IPAddress]::TryParse($networkParts[0], [ref]$parsedNetworkAddress) -or
    -not [int]::TryParse($networkParts[1], [ref]$parsedPrefix) -or
    $parsedNetworkAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
    $parsedPrefix -lt 8 -or
    $parsedPrefix -gt 32
) { throw 'allowed_network_invalid' }
$networkBytes = $parsedNetworkAddress.GetAddressBytes()
$privateNetwork = (
    $networkBytes[0] -eq 10 -or
    ($networkBytes[0] -eq 172 -and $networkBytes[1] -ge 16 -and $networkBytes[1] -le 31) -or
    ($networkBytes[0] -eq 192 -and $networkBytes[1] -eq 168) -or
    $networkBytes[0] -eq 127
)
if (-not $privateNetwork) { throw 'allowed_network_private_required' }

if (-not $TlsCertificatePath) { $TlsCertificatePath = Join-Path $resolvedRoot '.local-secrets\tls\lan-server.pem' }
if (-not $TlsKeyPath) { $TlsKeyPath = Join-Path $resolvedRoot '.local-secrets\tls\lan-server-key.pem' }
if (-not $TlsCaPath) { $TlsCaPath = Join-Path $resolvedRoot '.local-secrets\tls\lan-ca.pem' }
$tlsCertificate = Resolve-RequiredFile $TlsCertificatePath 'tls_certificate_not_found'
$tlsKey = Resolve-RequiredFile $TlsKeyPath 'tls_key_not_found'
$tlsCa = Resolve-RequiredFile $TlsCaPath 'tls_ca_not_found'
$python = Resolve-PythonExecutables $PythonPath

$argumentValues = @(
    $launcher,
    '--bind-host', $BindHost,
    '--advertise-host', $AdvertiseHost,
    '--api-port', [string]$ApiPort,
    '--docs-port', [string]$DocsPort,
    '--allowed-network', $AllowedNetwork,
    '--tls-cert-file', $tlsCertificate,
    '--tls-key-file', $tlsKey,
    '--tls-ca-file', $tlsCa
)
$quotedArguments = @($argumentValues | ForEach-Object { Quote-WindowsArgument ([string]$_) })
$actionArguments = $quotedArguments -join ' '
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name

$plan = [ordered]@{
    schemaVersion = 'multi_agent_memory.lan_host_task_plan.v1'
    taskName = $TaskName
    execute = $python.Task
    arguments = $actionArguments
    workingDirectory = $resolvedRoot
    principal = [ordered]@{
        userId = $identity
        logonType = 'Interactive'
        runLevel = 'Limited'
        storedPassword = $false
    }
    trigger = [ordered]@{
        type = 'AtLogOn'
        userId = $identity
    }
    settings = [ordered]@{
        startWhenAvailable = $true
        allowStartIfOnBatteries = $true
        dontStopIfGoingOnBatteries = $true
        multipleInstances = 'IgnoreNew'
        executionTimeLimit = 'PT0S'
        restartCount = 5
        restartInterval = 'PT1M'
    }
    secureBaseUrl = "https://${AdvertiseHost}:$ApiPort"
    documentationUrl = "http://${AdvertiseHost}:$DocsPort"
    tlsConfigured = $true
    valuesRedacted = $true
    rawCredentialExposed = $false
    rawPayloadExposed = $false
}

if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 8
    return
}

function Test-DesiredTask {
    param([object]$Task)
    if (-not $Task) { return $false }
    $actions = @($Task.Actions)
    $triggers = @($Task.Triggers)
    if ($actions.Count -ne 1 -or $triggers.Count -ne 1) { return $false }
    $action = $actions[0]
    $triggerName = [string]$triggers[0].CimClass.CimClassName
    $logonType = [string]$Task.Principal.LogonType
    return (
        (Test-SameText $action.Execute $python.Task) -and
        ([string]$action.Arguments -ceq $actionArguments) -and
        (Test-SameText $action.WorkingDirectory $resolvedRoot) -and
        (Test-SameAccount $Task.Principal.UserId $identity) -and
        ([string]$Task.Principal.RunLevel -match 'Limited|0') -and
        ($logonType -match 'Interactive|3') -and
        ($triggerName -eq 'MSFT_TaskLogonTrigger') -and
        [bool]$Task.Settings.StartWhenAvailable -and
        ([int]$Task.Settings.RestartCount -eq 5) -and
        ([string]$Task.Settings.RestartInterval -eq 'PT1M') -and
        ([string]$Task.Settings.MultipleInstances -match 'IgnoreNew|2')
    )
}

function Test-KnownLegacyTask {
    param([object]$Task)
    if (-not $Task -or @($Task.Actions).Count -ne 1) { return $false }
    $legacyPath = Join-Path $resolvedRoot 'var\lan-host\serve_lan.py'
    $legacyArguments = Quote-WindowsArgument $legacyPath
    return (
        (Test-SameText $Task.Actions[0].Execute $python.Task) -and
        ([string]$Task.Actions[0].Arguments -ceq $legacyArguments) -and
        (Test-SameText $Task.Actions[0].WorkingDirectory $resolvedRoot)
    )
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$registrationChanged = $false
if (-not (Test-DesiredTask $existing)) {
    if ($existing -and -not (Test-KnownLegacyTask $existing)) {
        throw 'scheduled_task_name_collision_or_unrecognized_drift'
    }
    if ($PSCmdlet.ShouldProcess($TaskName, 'Register bounded self-healing LAN host task')) {
        if ($existing -and $existing.State -eq 'Running') {
            Stop-ScheduledTask -TaskName $TaskName
        }
        $action = New-ScheduledTaskAction -Execute $python.Task -Argument $actionArguments -WorkingDirectory $resolvedRoot
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
        $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet `
            -StartWhenAvailable `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -MultipleInstances IgnoreNew `
            -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -RestartCount 5 `
            -RestartInterval (New-TimeSpan -Minutes 1)
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $action `
            -Trigger $trigger `
            -Principal $principal `
            -Settings $settings `
            -Description 'Tracked TLS-protected Multi-Agent Memory runtime and public documentation host.' `
            -Force | Out-Null
        $registrationChanged = $true
    }
}

if (-not $NoStart) {
    $current = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if ($current.State -ne 'Running' -and $PSCmdlet.ShouldProcess($TaskName, 'Start LAN host task')) {
        Start-ScheduledTask -TaskName $TaskName
    }
    $checkArguments = @($argumentValues + '--check')
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $ready = $false
    $lastCheck = $null
    do {
        Start-Sleep -Milliseconds 500
        $rendered = & $python.Console @checkArguments 2>$null
        if ($LASTEXITCODE -eq 0 -and $rendered) {
            try {
                $lastCheck = ($rendered -join "`n") | ConvertFrom-Json
                $ready = [bool]$lastCheck.ok
            }
            catch {
                $ready = $false
            }
        }
    } while (-not $ready -and (Get-Date) -lt $deadline)
    if (-not $ready) { throw 'lan_host_startup_health_check_failed' }
}

[ordered]@{
    ok = $true
    schemaVersion = 'multi_agent_memory.lan_host_task_install.v1'
    taskName = $TaskName
    registrationChanged = $registrationChanged
    running = if ($NoStart) { $false } else { (Get-ScheduledTask -TaskName $TaskName).State -eq 'Running' }
    secureBaseUrl = $plan.secureBaseUrl
    documentationUrl = $plan.documentationUrl
    tlsConfigured = $true
    valuesRedacted = $true
    rawCredentialExposed = $false
    rawPayloadExposed = $false
} | ConvertTo-Json -Depth 5
