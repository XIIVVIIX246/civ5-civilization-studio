[CmdletBinding()]
param(
    [string]$PythonPath = "",
    [switch]$SkipTests,
    [string]$SigningCertificateSha1 = "",
    [string]$SignToolPath = "",
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $PythonPath) {
    $PythonPath = Join-Path $RepoRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python was not found at '$PythonPath'. Create .venv and install .[dev] first."
}

$Version = (& $PythonPath -c "from importlib.metadata import version; print(version('civ5-civilization-studio'))").Trim()
if ($LASTEXITCODE -ne 0 -or -not $Version) {
    throw "Could not read the installed Civ5Studio package version."
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ArtifactName = "Civ5-Civilization-Studio-$Version-windows-x64"
$ReleaseRoot = Join-Path $RepoRoot "release"
$WorkRoot = Join-Path $RepoRoot "build\pyinstaller-$Stamp"
$SpecRoot = Join-Path $WorkRoot "spec"
$DistRoot = Join-Path $WorkRoot "dist"
New-Item -ItemType Directory -Force -Path $ReleaseRoot, $WorkRoot, $SpecRoot, $DistRoot | Out-Null

if (-not $SkipTests) {
    & $PythonPath -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed with exit code $LASTEXITCODE."
    }
}

$GitCommit = [string](& git -C $RepoRoot rev-parse HEAD 2>$null)
$GitCommit = $GitCommit.Trim()
if ($LASTEXITCODE -ne 0 -or -not $GitCommit) {
    throw "A Git commit is required for a traceable Windows release."
}
$GitStatus = @(& git -C $RepoRoot status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    throw "Could not verify the release worktree state."
}
if ($GitStatus.Count -gt 0) {
    throw "Refusing to package a dirty worktree: $($GitStatus -join '; ')"
}
$SourceDateEpoch = [string](& git -C $RepoRoot show -s --format=%ct HEAD 2>$null)
$SourceDateEpoch = $SourceDateEpoch.Trim()
if ($LASTEXITCODE -eq 0 -and $SourceDateEpoch) {
    $env:SOURCE_DATE_EPOCH = $SourceDateEpoch
}
$env:PYTHONHASHSEED = "0"

& $PythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name $ArtifactName `
    --distpath $DistRoot `
    --workpath $WorkRoot `
    --specpath $SpecRoot `
    --collect-data civ5studio `
    (Join-Path $RepoRoot "tools\frozen_entry.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

$ArtifactFolder = Join-Path $DistRoot $ArtifactName
$Executable = Join-Path $ArtifactFolder "$ArtifactName.exe"
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "The expected executable was not produced: $Executable"
}

$Probe = Start-Process `
    -FilePath $Executable `
    -ArgumentList "--version" `
    -WindowStyle Hidden `
    -Wait `
    -PassThru
if ($Probe.ExitCode -ne 0) {
    throw "Frozen executable version probe failed with exit code $($Probe.ExitCode)."
}

$UiProbe = Start-Process `
    -FilePath $Executable `
    -ArgumentList "--smoke-test" `
    -WindowStyle Hidden `
    -Wait `
    -PassThru
if ($UiProbe.ExitCode -ne 0) {
    throw "Frozen executable UI smoke probe failed with exit code $($UiProbe.ExitCode)."
}

# A public release carries the original-code license, third-party notices,
# complete upstream license texts, provenance, and privacy/support guidance.
Copy-Item -LiteralPath (Join-Path $RepoRoot "LICENSE") -Destination $ArtifactFolder
Copy-Item -LiteralPath (Join-Path $RepoRoot "THIRD_PARTY_NOTICES.md") -Destination $ArtifactFolder
Copy-Item -LiteralPath (Join-Path $RepoRoot "docs\PUBLIC_RELEASE.md") -Destination $ArtifactFolder
Copy-Item -LiteralPath (Join-Path $RepoRoot "docs\SOURCE_PROVENANCE.md") -Destination $ArtifactFolder
Copy-Item -LiteralPath (Join-Path $RepoRoot "licenses") -Destination $ArtifactFolder -Recurse

$SigningStatus = "UNSIGNED_PUBLIC_CANDIDATE"
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
        /tr $TimestampUrl /td SHA256 $Executable
    if ($LASTEXITCODE -ne 0) {
        throw "Application Authenticode signing failed."
    }
    & $SignToolPath verify /pa /v $Executable
    if ($LASTEXITCODE -ne 0) {
        throw "Application Authenticode verification failed."
    }
    $SigningStatus = "SIGNED_TIMESTAMPED_AND_VERIFIED"
}
[System.IO.File]::WriteAllText(
    (Join-Path $ArtifactFolder "SIGNING_STATUS.txt"),
    "$SigningStatus`n",
    [System.Text.UTF8Encoding]::new($false)
)
$ReleaseChannel = if ($SigningCertificateSha1) { "public" } else { "public-candidate-unsigned" }

$ZipPath = Join-Path $ReleaseRoot "$ArtifactName-$ReleaseChannel-$Stamp.zip"
$PackageJson = & $PythonPath `
    (Join-Path $RepoRoot "tools\package_windows_release.py") `
    $ArtifactFolder `
    $ZipPath `
    --version $Version `
    --git-commit $GitCommit
if ($LASTEXITCODE -ne 0) {
    throw "Release packaging failed with exit code $LASTEXITCODE."
}
$Package = $PackageJson | ConvertFrom-Json

& $PythonPath (Join-Path $RepoRoot "tools\verify_public_release.py") $ZipPath
if ($LASTEXITCODE -ne 0) {
    throw "Public release verification failed with exit code $LASTEXITCODE."
}

$PublishedFolder = Join-Path $ReleaseRoot "$ArtifactName-$ReleaseChannel-$Stamp"
if (Test-Path -LiteralPath $PublishedFolder) {
    throw "Refusing to overwrite release folder: $PublishedFolder"
}
$ResolvedArtifact = [System.IO.Path]::GetFullPath($ArtifactFolder)
$ResolvedDist = [System.IO.Path]::GetFullPath($DistRoot) + [System.IO.Path]::DirectorySeparatorChar
$ResolvedPublished = [System.IO.Path]::GetFullPath($PublishedFolder)
$ResolvedRelease = [System.IO.Path]::GetFullPath($ReleaseRoot) + [System.IO.Path]::DirectorySeparatorChar
if (-not $ResolvedArtifact.StartsWith($ResolvedDist, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Frozen artifact escaped the project build directory."
}
if (-not $ResolvedPublished.StartsWith($ResolvedRelease, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Published artifact escaped the project release directory."
}
Move-Item -LiteralPath $ArtifactFolder -Destination $PublishedFolder
$Executable = Join-Path $PublishedFolder "$ArtifactName.exe"

[pscustomobject]@{
    Version = $Version
    GitCommit = $GitCommit
    Executable = $Executable
    Manifest = Join-Path $PublishedFolder "RELEASE_MANIFEST.json"
    Zip = $Package.zip
    Sha256 = $Package.sha256
    Sha256File = $Package.sha256_file
    SigningStatus = $SigningStatus
}
