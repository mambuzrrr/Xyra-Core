[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$BuildInstaller,
    [switch]$Sign,
    [string]$CertificateThumbprint = $env:XYRA_SIGN_CERT_THUMBPRINT,
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [ValidateSet("stable", "prerelease")]
    [string]$UpdateChannel = "stable",
    [string]$UpdateArtifactUrl = "",
    [string]$ReleaseNotesUrl = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$artifactDir = Join-Path $projectRoot "release_artifacts"
$workDir = Join-Path $projectRoot "build\release"
$stagingDir = Join-Path $artifactDir "staging"

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program failed with exit code $LASTEXITCODE"
    }
}

function Find-SignTool {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $kits = "C:\Program Files (x86)\Windows Kits\10\bin"
    if (Test-Path -LiteralPath $kits) {
        $candidate = Get-ChildItem -LiteralPath $kits -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($candidate) { return $candidate.FullName }
    }
    return $null
}

function Find-InnoCompiler {
    $command = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if (-not $command) { $command = Get-Command iscc -ErrorAction SilentlyContinue }
    if ($command) { return $command.Source }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}

function Sign-ReleaseFile {
    param([string]$Path)
    if (-not $Sign) { return }
    if (-not $CertificateThumbprint) {
        throw "Signing requested, but no certificate thumbprint was supplied."
    }
    $signTool = Find-SignTool
    if (-not $signTool) {
        throw "Signing requested, but Windows SignTool was not found."
    }
    Invoke-Checked $signTool @(
        "sign", "/sha1", $CertificateThumbprint, "/fd", "SHA256",
        "/tr", $TimestampUrl, "/td", "SHA256", $Path
    )
    Invoke-Checked $signTool @("verify", "/pa", "/all", "/v", $Path)
}

Set-Location $projectRoot
if (-not [Environment]::Is64BitProcess) {
    throw "The Xyra x64 release must be built with 64-bit Python."
}

$metadataJson = & python (Join-Path $projectRoot "scripts\validate_release.py")
if ($LASTEXITCODE -ne 0) { throw "Release metadata validation failed." }
$metadata = $metadataJson | ConvertFrom-Json
$version = $metadata.version
$releaseExe = Join-Path $artifactDir "Xyra-$version-x64.exe"
$setup = Join-Path $artifactDir "Xyra-Setup-$version-x64.exe"
$manifestPath = Join-Path $artifactDir "release-manifest-$version.json"

if (-not $SkipTests) {
    $testDir = Join-Path $projectRoot "tests"
    if (Test-Path -LiteralPath $testDir -PathType Container) {
        Invoke-Checked "python" @("-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-q")
    }
    else {
        Write-Warning "Local test suite not found. Continuing without tests."
    }
}

foreach ($path in @($workDir, $stagingDir)) {
    $resolvedParent = [IO.Path]::GetFullPath((Split-Path -Parent $path))
    if (-not $resolvedParent.StartsWith([IO.Path]::GetFullPath($projectRoot), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a release path outside the project: $path"
    }
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}
New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null
New-Item -ItemType Directory -Path $stagingDir -Force | Out-Null
foreach ($oldOutput in @($releaseExe, $setup, $manifestPath)) {
    if (Test-Path -LiteralPath $oldOutput) {
        try {
            Remove-Item -LiteralPath $oldOutput -Force
        } catch {
            throw "Cannot replace release output '$oldOutput'. Close any running Xyra or installer process and retry."
        }
    }
}

$env:PYTHONHASHSEED = "0"
Invoke-Checked "python" @(
    "-m", "PyInstaller", "--noconfirm", "--clean",
    "--workpath", $workDir, "--distpath", $stagingDir, "Xyra.spec"
)

$builtExe = Join-Path $stagingDir "Xyra.exe"
if (-not (Test-Path -LiteralPath $builtExe -PathType Leaf)) {
    throw "PyInstaller did not create Xyra.exe"
}
Copy-Item -LiteralPath $builtExe -Destination $releaseExe -Force
Sign-ReleaseFile $releaseExe

$outputs = @($releaseExe)
if ($BuildInstaller) {
    $iscc = Find-InnoCompiler
    if (-not $iscc) {
        throw "Installer requested, but Inno Setup (ISCC) is not installed or not on PATH."
    }
    $iss = Join-Path $projectRoot "installer\Xyra.iss"
    Invoke-Checked $iscc @(
        "/DAppVersion=$version", "/DSourceExe=$releaseExe",
        "/DOutputDir=$artifactDir", $iss
    )
    if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) {
        throw "Inno Setup did not create the expected installer."
    }
    Sign-ReleaseFile $setup
    $outputs += $setup
}

if ($UpdateArtifactUrl) {
    if (-not $BuildInstaller) {
        throw "A signed update manifest requires -BuildInstaller."
    }
    if (-not $ReleaseNotesUrl) {
        throw "A signed update manifest requires -ReleaseNotesUrl."
    }
    $updateManifest = Join-Path $artifactDir "update-$UpdateChannel-$version.json"
    Invoke-Checked "python" @(
        "scripts\sign_update_manifest.py",
        "--channel", $UpdateChannel,
        "--version", $version,
        "--artifact", $setup,
        "--url", $UpdateArtifactUrl,
        "--notes-url", $ReleaseNotesUrl,
        "--output", $updateManifest
    )
}

$manifest = foreach ($file in $outputs) {
    $signature = Get-AuthenticodeSignature -LiteralPath $file
    [ordered]@{
        file = Split-Path -Leaf $file
        bytes = (Get-Item -LiteralPath $file).Length
        sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        signatureStatus = [string]$signature.Status
        signer = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
    }
}
[ordered]@{
    product = "Xyra"
    version = $version
    architecture = "x64"
    signed = [bool]$Sign
    files = @($manifest)
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "Release build complete: $artifactDir"
Write-Host "Manifest: $manifestPath"
