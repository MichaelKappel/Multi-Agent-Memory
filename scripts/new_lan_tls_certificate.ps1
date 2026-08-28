#requires -Version 7.2
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$AdvertiseHost,

    [string]$DnsName = $env:COMPUTERNAME,

    [string]$OutputDirectory = '',

    [ValidateRange(1, 825)]
    [int]$ValidDays = 825,

    [switch]$Force
)

$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) '.local-secrets\tls'
}

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [IO.Path]::GetFullPath($Path)
}

function Set-PrivateAcl {
    param([Parameter(Mandatory = $true)][string]$Path)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $Path /inheritance:r /grant:r "${identity}:(OI)(CI)(F)" 'NT AUTHORITY\SYSTEM:(OI)(CI)(F)' 'BUILTIN\Administrators:(OI)(CI)(F)' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'tls_acl_restriction_failed'
    }
}

$advertiseAddress = $null
if (-not [Net.IPAddress]::TryParse($AdvertiseHost, [ref]$advertiseAddress)) {
    throw 'advertise_host_must_be_ip_literal'
}
if ($advertiseAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'advertise_host_must_be_ipv4'
}

$outputRoot = Resolve-FullPath $OutputDirectory
$caPemPath = Join-Path $outputRoot 'lan-ca.pem'
$caDerPath = Join-Path $outputRoot 'lan-ca.cer'
$serverPemPath = Join-Path $outputRoot 'lan-server.pem'
$serverKeyPath = Join-Path $outputRoot 'lan-server-key.pem'
$targets = @($caPemPath, $caDerPath, $serverPemPath, $serverKeyPath)
if (-not $Force -and @($targets | Where-Object { Test-Path -LiteralPath $_ }).Count -gt 0) {
    throw 'tls_output_exists_refusing_overwrite'
}

if (-not $PSCmdlet.ShouldProcess($outputRoot, 'Create and trust a private LAN certificate authority and server certificate')) {
    return
}

New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
Set-PrivateAcl $outputRoot

$caKey = [Security.Cryptography.RSA]::Create(3072)
$serverKey = [Security.Cryptography.RSA]::Create(3072)
$caCertificate = $null
$serverCertificate = $null
try {
    $hash = [Security.Cryptography.HashAlgorithmName]::SHA256
    $padding = [Security.Cryptography.RSASignaturePadding]::Pkcs1
    $caRequest = [Security.Cryptography.X509Certificates.CertificateRequest]::new(
        'CN=Multi-Agent Memory Private LAN CA',
        $caKey,
        $hash,
        $padding
    )
    $caRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($true, $true, 0, $true)
    )
    $caRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new(
            [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyCertSign -bor
            [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::CrlSign,
            $true
        )
    )
    $caRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509SubjectKeyIdentifierExtension]::new($caRequest.PublicKey, $false)
    )
    $now = [DateTimeOffset]::UtcNow
    $caCertificate = $caRequest.CreateSelfSigned($now.AddMinutes(-5), $now.AddYears(10))

    $serverRequest = [Security.Cryptography.X509Certificates.CertificateRequest]::new(
        'CN=Multi-Agent Memory LAN Host',
        $serverKey,
        $hash,
        $padding
    )
    $serverRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($false, $false, 0, $true)
    )
    $serverRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new(
            [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature -bor
            [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyEncipherment,
            $true
        )
    )
    $enhancedUsage = [Security.Cryptography.OidCollection]::new()
    [void]$enhancedUsage.Add([Security.Cryptography.Oid]::new('1.3.6.1.5.5.7.3.1'))
    $serverRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new($enhancedUsage, $true)
    )
    $san = [Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
    $san.AddIpAddress([Net.IPAddress]::Loopback)
    $san.AddIpAddress($advertiseAddress)
    $san.AddDnsName('localhost')
    if ($DnsName -and $DnsName -match '^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$') {
        $san.AddDnsName($DnsName)
    }
    $serverRequest.CertificateExtensions.Add($san.Build($true))
    $serverRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509SubjectKeyIdentifierExtension]::new($serverRequest.PublicKey, $false)
    )
    $serverRequest.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509AuthorityKeyIdentifierExtension]::CreateFromCertificate(
            $caCertificate,
            $true,
            $false
        )
    )
    $serial = [byte[]]::new(16)
    [Security.Cryptography.RandomNumberGenerator]::Fill($serial)
    $serial[0] = $serial[0] -band 0x7F
    $issued = $serverRequest.Create(
        $caCertificate,
        $now.AddMinutes(-5),
        $now.AddDays($ValidDays),
        $serial
    )
    $serverCertificate = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::CopyWithPrivateKey(
        $issued,
        $serverKey
    )
    $issued.Dispose()

    $utf8NoBom = [Text.UTF8Encoding]::new($false)
    [IO.File]::WriteAllText($caPemPath, $caCertificate.ExportCertificatePem(), $utf8NoBom)
    [IO.File]::WriteAllBytes(
        $caDerPath,
        $caCertificate.Export([Security.Cryptography.X509Certificates.X509ContentType]::Cert)
    )
    [IO.File]::WriteAllText(
        $serverPemPath,
        $serverCertificate.ExportCertificatePem() + [Environment]::NewLine + $caCertificate.ExportCertificatePem(),
        $utf8NoBom
    )
    [IO.File]::WriteAllText($serverKeyPath, $serverKey.ExportPkcs8PrivateKeyPem(), $utf8NoBom)
    Set-PrivateAcl $outputRoot

    & certutil.exe -user -f -addstore Root $caDerPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'tls_ca_trust_install_failed' }
    if ($Force) {
        $otherCertificates = @(Get-ChildItem Cert:\CurrentUser\Root | Where-Object {
            $_.Subject -eq 'CN=Multi-Agent Memory Private LAN CA' -and
            $_.Thumbprint -ne $caCertificate.Thumbprint
        })
        foreach ($otherCertificate in $otherCertificates) {
            & certutil.exe -user -delstore Root $otherCertificate.Thumbprint | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'stale_tls_ca_removal_failed' }
        }
    }

    [ordered]@{
        ok = $true
        schemaVersion = 'multi_agent_memory.lan_tls_setup.v1'
        advertiseHost = $advertiseAddress.ToString()
        caCertificatePath = $caDerPath
        caPemPath = $caPemPath
        serverCertificatePath = $serverPemPath
        serverKeyPath = $serverKeyPath
        caSha256Fingerprint = $caCertificate.GetCertHashString([Security.Cryptography.HashAlgorithmName]::SHA256)
        trustedForCurrentWindowsUser = $true
        valuesRedacted = $true
        rawCredentialExposed = $false
        rawPayloadExposed = $false
    } | ConvertTo-Json -Depth 4
}
finally {
    if ($serverCertificate) { $serverCertificate.Dispose() }
    if ($caCertificate) { $caCertificate.Dispose() }
    $serverKey.Dispose()
    $caKey.Dispose()
}
