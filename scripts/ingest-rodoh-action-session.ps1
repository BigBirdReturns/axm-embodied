[CmdletBinding(DefaultParameterSetName = "Local")]
param(
    [Parameter(Mandatory = $true, ParameterSetName = "Local")]
    [string]$SpoolPath,

    [Parameter(Mandatory = $true, ParameterSetName = "Quest")]
    [string]$RemoteSpoolPath,

    [Parameter(ParameterSetName = "Quest")]
    [string]$QuestSerial,

    [Parameter(ParameterSetName = "Quest")]
    [string]$Adb = "adb",

    [Parameter(Mandatory = $true)]
    [string]$JournalPath,

    [string]$PullRoot,
    [string]$Python,
    [string]$AcceptedReceipt,
    [switch]$KeepPulledSpool
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-FullPath([string]$Value, [string]$Base) {
    if ([System.IO.Path]::IsPathRooted($Value)) { return [System.IO.Path]::GetFullPath($Value) }
    return [System.IO.Path]::GetFullPath((Join-Path $Base $Value))
}

function Invoke-Checked([string]$File, [string[]]$Arguments, [string]$Label) {
    Write-Host $Label
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit $LASTEXITCODE." }
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if ([string]::IsNullOrWhiteSpace($Python)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}
$pythonPath = [System.IO.Path]::GetFullPath($Python)
$journal = Resolve-FullPath $JournalPath (Get-Location).Path
$pulled = $false

if ($PSCmdlet.ParameterSetName -eq "Quest") {
    $adbCommand = (Get-Command $Adb -ErrorAction Stop).Source
    if ([string]::IsNullOrWhiteSpace($PullRoot)) {
        $PullRoot = Join-Path $repoRoot "local\quest-action-spools"
    }
    $pullBase = Resolve-FullPath $PullRoot $repoRoot
    New-Item -ItemType Directory -Force $pullBase | Out-Null
    $sessionName = [System.IO.Path]::GetFileName($RemoteSpoolPath.TrimEnd('/', '\'))
    if ([string]::IsNullOrWhiteSpace($sessionName)) { $sessionName = "quest-action-session" }
    $localSpool = Join-Path $pullBase $sessionName
    if (Test-Path $localSpool) {
        throw "Refusing to replace an existing pulled spool: $localSpool"
    }
    $adbArguments = @()
    if (-not [string]::IsNullOrWhiteSpace($QuestSerial)) {
        $adbArguments += @("-s", $QuestSerial)
    }
    Invoke-Checked $adbCommand ($adbArguments + @("get-state")) "Checking Quest ADB connectivity..."
    Invoke-Checked $adbCommand ($adbArguments + @("pull", $RemoteSpoolPath, $localSpool)) "Pulling the immutable Quest action spool..."
    $SpoolPath = $localSpool
    $pulled = $true
}

$spool = Resolve-FullPath $SpoolPath (Get-Location).Path
if (-not (Test-Path (Join-Path $spool "session-start.json"))) { throw "Action spool start is absent: $spool" }
if (-not (Test-Path (Join-Path $spool "index.json"))) { throw "Action spool index is absent: $spool" }

$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    Join-Path $repoRoot "src"
} else {
    (Join-Path $repoRoot "src") + [System.IO.Path]::PathSeparator + $env:PYTHONPATH
}

Invoke-Checked $pythonPath @(
    "-m", "axm_embodied.action_spool",
    $spool,
    $journal
) "Ingesting the Unity or Quest action spool into the embodied journal..."

if (-not [string]::IsNullOrWhiteSpace($AcceptedReceipt)) {
    $receipt = Resolve-FullPath $AcceptedReceipt (Get-Location).Path
    if (-not (Test-Path $receipt)) { throw "Accepted Arc action receipt is absent: $receipt" }
    Invoke-Checked $pythonPath @(
        "-m", "axm_embodied.action_session",
        "attach-receipt",
        $journal,
        $receipt
    ) "Attaching the Arc-owned accepted action receipt..."
}

Invoke-Checked $pythonPath @(
    "-m", "axm_embodied.action_session",
    "verify",
    $journal
) "Verifying the complete embodied action-session chain..."

$shardPath = Join-Path $journal "genesis-shard.json"
Invoke-Checked $pythonPath @(
    "-m", "axm_embodied.action_session",
    "shard",
    $journal,
    "--output", $shardPath
) "Projecting the Genesis-facing custody shard..."

$receiptObject = [ordered]@{
    format = "axm-embodied-action-session-ingest-run/1"
    generatedAt = (Get-Date).ToUniversalTime().ToString("o")
    status = "pass"
    source = if ($PSCmdlet.ParameterSetName -eq "Quest") { "quest-adb" } else { "local-spool" }
    questSerial = if ($PSCmdlet.ParameterSetName -eq "Quest") { $QuestSerial } else { $null }
    remoteSpoolPath = if ($PSCmdlet.ParameterSetName -eq "Quest") { $RemoteSpoolPath } else { $null }
    spoolPath = $spool
    journalPath = $journal
    acceptedReceipt = if ([string]::IsNullOrWhiteSpace($AcceptedReceipt)) { $null } else { [System.IO.Path]::GetFullPath($AcceptedReceipt) }
    genesisShard = $shardPath
}
$runReceipt = Join-Path $journal "ingest-run.json"
$receiptObject | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 $runReceipt

if ($pulled -and -not $KeepPulledSpool) {
    Write-Host "The pulled spool remains at $spool until the journal receipt is independently backed up. It was not deleted automatically."
}
Write-Host "RODOH embodied action-session ingestion passed."
Write-Host $runReceipt
