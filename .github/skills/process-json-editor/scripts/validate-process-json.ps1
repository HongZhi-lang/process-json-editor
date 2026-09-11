[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Leaf })]
    [string]$Path
)

$ErrorActionPreference = 'Stop'
$validator = Join-Path $PSScriptRoot '..\tools\proc-indexer\src\validate.mjs'
$resolvedPath = (Resolve-Path $Path).Path

& node $validator $resolvedPath
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
