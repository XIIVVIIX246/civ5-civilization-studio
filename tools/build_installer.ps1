[CmdletBinding()]
param(
    [string]$FrozenFolder = "",
    [string]$InnoCompiler = "",
    [string]$SigningCertificateSha1 = "",
    [string]$SignToolPath = "",
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ReleaseRoot = Join-Path $RepoRoot "release"
$InstallerScript = Join-Path $RepoRoot "packaging\Civ5CivilizationStudio.iss"
$PyprojectPath = Join-Path $RepoRoot "pyproject.toml"
$PackageInitPath = Join-Path $RepoRoot "src\civ5studio\__init__.py"

if (-not (Test-Path -LiteralPath $InstallerScript -PathType Leaf)) {
    throw "Installer definition was not found: $InstallerScript"
}

$GitCommit = [string](& git -C $RepoRoot rev-parse HEAD 2>$null)
$GitCommit = $GitCommit.Trim()
if ($LASTEXITCODE -ne 0 -or -not $GitCommit) {
    throw "A Git commit is required for a traceable installer."
}
$GitStatus = @(& git -C $RepoRoot status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    throw "Could not verify the installer worktree state."
}
if ($GitStatus.Count -gt 0) {
    throw "Refusing to package a dirty worktree: $($GitStatus -join '; ')"
}

if (-not $FrozenFolder) {
    $candidate = Get-ChildItem -LiteralPath $ReleaseRoot -Directory `
        -Filter "Civ5-Civilization-Studio-*-windows-x64-*" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $candidate) {
        throw "No frozen release folder exists. Run tools\build_windows.ps1 first."
    }
    $FrozenFolder = $candidate.FullName
}
$FrozenFolder = (Resolve-Path -LiteralPath $FrozenFolder).Path
$ResolvedRelease = [System.IO.Path]::GetFullPath($ReleaseRoot) + [System.IO.Path]::DirectorySeparatorChar
if (-not $FrozenFolder.StartsWith($ResolvedRelease, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The frozen application must be a project-owned release folder."
}

$ManifestPath = Join-Path $FrozenFolder "RELEASE_MANIFEST.json"
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "Frozen release lacks RELEASE_MANIFEST.json: $FrozenFolder"
}
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$Version = [string]$Manifest.application_version
if (-not $Version -or $Manifest.git_commit -ne $GitCommit) {
    throw "Frozen release manifest does not match the current Git commit."
}
if ($Version -notmatch '^\d+\.\d+\.\d+(?:\.\d+)?$') {
    throw "Frozen release has an unsupported installer version: '$Version'."
}
$PyprojectText = Get-Content -LiteralPath $PyprojectPath -Raw
$InitText = Get-Content -LiteralPath $PackageInitPath -Raw
$PyprojectVersionMatch = [regex]::Match(
    $PyprojectText,
    '(?m)^version\s*=\s*"(?<version>[^"]+)"\s*$'
)
$InitVersionMatch = [regex]::Match(
    $InitText,
    '(?m)^__version__\s*=\s*"(?<version>[^"]+)"\s*$'
)
if (-not $PyprojectVersionMatch.Success -or -not $InitVersionMatch.Success) {
    throw "Could not read both source version declarations."
}
$PyprojectVersion = $PyprojectVersionMatch.Groups['version'].Value
$InitVersion = $InitVersionMatch.Groups['version'].Value
if ($Version -ne $PyprojectVersion -or $Version -ne $InitVersion) {
    throw "Release version mismatch: manifest=$Version, pyproject=$PyprojectVersion, module=$InitVersion."
}
$Executable = Get-ChildItem -LiteralPath $FrozenFolder -File `
    -Filter "Civ5-Civilization-Studio-*-windows-x64.exe"
if (@($Executable).Count -ne 1) {
    throw "Frozen release must contain exactly one Civilization Studio executable."
}
$Executable = @($Executable)[0]
$ExpectedExecutableName = "Civ5-Civilization-Studio-$Version-windows-x64.exe"
if ($Executable.Name -ne $ExpectedExecutableName) {
    throw "Frozen executable name does not match release version: $($Executable.Name)"
}

if (-not $InnoCompiler) {
    $compilerCandidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
    $InnoCompiler = $compilerCandidates | Select-Object -First 1
}
if (-not $InnoCompiler -or -not (Test-Path -LiteralPath $InnoCompiler -PathType Leaf)) {
    throw "Inno Setup 6 compiler not found. Supply -InnoCompiler with ISCC.exe."
}

$InstallerPath = Join-Path $ReleaseRoot "Civ5-Civilization-Studio-$Version-Setup.exe"
$HashPath = "$InstallerPath.sha256.txt"
if (Test-Path -LiteralPath $InstallerPath -PathType Leaf) {
    throw "Refusing to overwrite installer: $InstallerPath"
}
if (Test-Path -LiteralPath $HashPath -PathType Leaf) {
    throw "Refusing to overwrite installer hash: $HashPath"
}

& $InnoCompiler `
    "/DAppVersion=$Version" `
    "/DSourceDir=$FrozenFolder" `
    "/DAppExeName=$($Executable.Name)" `
    "/DOutputDir=$ReleaseRoot" `
    $InstallerScript
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "Inno Setup failed to produce the expected installer."
}

$SigningStatus = "UNSIGNED_NO_CERTIFICATE"
if ($SigningCertificateSha1) {
    if (-not $SignToolPath) {
        $signTool = Get-Command signtool.exe -ErrorAction SilentlyContinue
        if ($signTool) {
            $SignToolPath = $signTool.Source
        }
    }
    if (-not $SignToolPath) {
        $sdkRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
        if (Test-Path -LiteralPath $sdkRoot -PathType Container) {
            $SignToolPath = Get-ChildItem -LiteralPath $sdkRoot -Directory |
                Sort-Object Name -Descending |
                ForEach-Object { Join-Path $_.FullName "x64\signtool.exe" } |
                Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
                Select-Object -First 1
        }
    }
    if (-not $SignToolPath -or -not (Test-Path -LiteralPath $SignToolPath -PathType Leaf)) {
        throw "A certificate thumbprint was supplied but signtool.exe was not found."
    }
    & $SignToolPath sign /sha1 $SigningCertificateSha1 /fd SHA256 `
        /tr $TimestampUrl /td SHA256 $InstallerPath
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode signing failed."
    }
    & $SignToolPath verify /pa /v $InstallerPath
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode verification failed."
    }
    $SigningStatus = "SIGNED_AND_VERIFIED"
}

$Hash = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText(
    $HashPath,
    "$Hash  $([System.IO.Path]::GetFileName($InstallerPath))`n",
    [System.Text.UTF8Encoding]::new($false)
)

[pscustomobject]@{
    Version = $Version
    GitCommit = $GitCommit
    Installer = $InstallerPath
    Sha256 = $Hash
    Sha256File = $HashPath
    SigningStatus = $SigningStatus
}
