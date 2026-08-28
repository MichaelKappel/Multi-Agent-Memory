#requires -Version 5.1
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)]
    [string]$CertificatePath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Fa-f0-9 :\-]{64,95}$')]
    [string]$ExpectedSha256Fingerprint
)

$ErrorActionPreference = 'Stop'

$resolved = Resolve-Path -LiteralPath $CertificatePath -ErrorAction SilentlyContinue
if (-not $resolved -or -not (Test-Path -LiteralPath $resolved.Path -PathType Leaf)) {
    throw 'lan_ca_certificate_not_found'
}
$certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new(
    [IO.Path]::GetFullPath($resolved.Path)
)
try {
    $expected = ($ExpectedSha256Fingerprint -replace '[^A-Fa-f0-9]', '').ToUpperInvariant()
    $actual = $certificate.GetCertHashString(
        [Security.Cryptography.HashAlgorithmName]::SHA256
    ).ToUpperInvariant()
    $difference = $expected.Length -bxor $actual.Length
    if ($expected.Length -eq $actual.Length) {
        for ($index = 0; $index -lt $expected.Length; $index++) {
            $difference = $difference -bor ([int]$expected[$index] -bxor [int]$actual[$index])
        }
    }
    if ($expected.Length -ne 64 -or $difference -ne 0) {
        throw 'lan_ca_sha256_fingerprint_mismatch'
    }
    if ([DateTime]::UtcNow -lt $certificate.NotBefore.ToUniversalTime() -or [DateTime]::UtcNow -gt $certificate.NotAfter.ToUniversalTime()) {
        throw 'lan_ca_certificate_not_currently_valid'
    }
    $basicConstraints = @($certificate.Extensions | Where-Object {
        $_ -is [Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]
    })
    if ($basicConstraints.Count -ne 1 -or -not $basicConstraints[0].CertificateAuthority -or -not $basicConstraints[0].Critical) {
        throw 'lan_ca_basic_constraints_invalid'
    }
    if (-not $certificate.Subject.StartsWith('CN=Multi-Agent Memory Private LAN CA', [StringComparison]::Ordinal)) {
        throw 'lan_ca_subject_unexpected'
    }

    if ($PSCmdlet.ShouldProcess(
        'CurrentUser\Trusted Root Certification Authorities',
        'Trust the fingerprint-verified Multi-Agent Memory private LAN CA'
    )) {
        & certutil.exe -user -f -addstore Root $resolved.Path | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'lan_ca_trust_install_failed' }
    }

    $trusted = @(Get-ChildItem Cert:\CurrentUser\Root | Where-Object {
        $_.Thumbprint -eq $certificate.Thumbprint
    }).Count -eq 1
    if (-not $trusted -and -not $WhatIfPreference) {
        throw 'lan_ca_trust_readback_failed'
    }

    [ordered]@{
        ok = $true
        schemaVersion = 'multi_agent_memory.lan_client_trust.v1'
        trustedForCurrentWindowsUser = $trusted
        fingerprintVerified = $true
        certificateAuthorityVerified = $true
        valuesRedacted = $true
        rawCredentialExposed = $false
        rawPayloadExposed = $false
    } | ConvertTo-Json -Depth 4
}
finally {
    $certificate.Dispose()
}
