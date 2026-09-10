[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Container })]
    [string]$Dir,

    [Parameter(Mandatory = $true)]
    [string]$EnvId,

    [Parameter(Mandatory = $true)]
    [string]$Version
)

function Get-ExportName {
    param([string]$FileName)

    if ($FileName -like 'ADV_*.json') {
        $advSuffix = [System.IO.Path]::GetFileNameWithoutExtension($FileName).Substring(4)
        return "ADV_$($advSuffix.Replace('_', '*')).json"
    }

    return $FileName
}

$consistencyPath = Join-Path $Dir 'CONSISTENCY.MD5'
$readmePath = Join-Path $Dir 'README.md'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

[System.IO.File]::WriteAllLines($consistencyPath, @("env:$EnvId", "version:$Version"), $utf8NoBom)
[System.IO.File]::WriteAllText($readmePath, '', $utf8NoBom)

$orderedFiles = Get-ChildItem -Path $Dir -File | Where-Object {
    $_.Name -notin @('CONSISTENCY.MD5', 'README.md') -and $_.Extension -ine '.jar'
} | Sort-Object @{ Expression = {
    if ($_.Name -like 'PROC_*.json') { 0 }
    elseif ($_.Name -like 'ADV_*.json') { 1 }
    else { 2 }
} }, Name

foreach ($file in $orderedFiles) {
    $rawBytes = [System.IO.File]::ReadAllBytes($file.FullName)
    $content = [System.Text.Encoding]::UTF8.GetString($rawBytes)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($content)
    $md5 = [System.Security.Cryptography.MD5]::Create()
    try {
        $hashBytes = $md5.ComputeHash($bytes)
        $hash = -join ($hashBytes | ForEach-Object { $_.ToString('x2') })
    } finally {
        $md5.Dispose()
    }

    $exportName = Get-ExportName -FileName $file.Name
    if (Test-Path $readmePath) {
        [System.IO.File]::AppendAllText($readmePath, "$exportName`r`n", $utf8NoBom)
    }
    [System.IO.File]::AppendAllText($consistencyPath, "${exportName}:$hash`r`n", $utf8NoBom)
}
