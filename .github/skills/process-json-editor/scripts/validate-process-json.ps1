[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Leaf })]
    [string]$Path
)

$ErrorActionPreference = 'Stop'
$errors = New-Object System.Collections.Generic.List[string]

function Add-ValidationError {
    param([string]$Message)
    [void]$errors.Add($Message)
}

try {
    $raw = [System.IO.File]::ReadAllText((Resolve-Path $Path), [System.Text.Encoding]::UTF8)
    $data = $raw | ConvertFrom-Json
} catch {
    Add-ValidationError "JSON cannot be parsed: $($_.Exception.Message)"
}

if ($null -ne $data) {
    if ($null -eq $data.processInfo) {
        Add-ValidationError 'Missing processInfo.'
    }

    $xml = New-Object System.Xml.XmlDocument
    try {
        $xml.LoadXml([string]$data.processInfo.processXml)
    } catch {
        Add-ValidationError "processInfo.processXml cannot be parsed: $($_.Exception.Message)"
    }

    if ($xml.DocumentElement) {
        $namespaceManager = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
        $namespaceManager.AddNamespace('bpmn', 'http://www.omg.org/spec/BPMN/20100524/MODEL')

        $xmlNodesById = @{}
        foreach ($element in $xml.SelectNodes('//*[@id]')) {
            $id = [string]$element.GetAttribute('id')
            if ($xmlNodesById.ContainsKey($id)) {
                Add-ValidationError "Duplicate XML id: $id"
            } else {
                $xmlNodesById[$id] = $element
            }
        }

        $sequenceFlowsById = @{}
        foreach ($flow in $xml.SelectNodes('//bpmn:sequenceFlow', $namespaceManager)) {
            $sequenceFlowsById[[string]$flow.GetAttribute('id')] = $flow
        }

        foreach ($node in @($data.nodeConf)) {
            $nodeId = [string]$node.actNodeId
            if ([string]::IsNullOrWhiteSpace($nodeId)) {
                Add-ValidationError 'nodeConf contains an entry without actNodeId.'
                continue
            }

            if (-not $xmlNodesById.ContainsKey($nodeId)) {
                Add-ValidationError "nodeConf actNodeId does not exist in processXml: $nodeId"
                continue
            }

            $xmlNode = $xmlNodesById[$nodeId]
            $xmlName = [string]$xmlNode.GetAttribute('name')
            if ($xmlName -and ([string]$node.actNodeName -ne $xmlName)) {
                Add-ValidationError "Node name mismatch for ${nodeId}: nodeConf='$($node.actNodeName)', XML='$xmlName'"
            }

            foreach ($apply in @($node.applyConf)) {
                $lineId = [string]$apply.actLineId
                if ($lineId -and -not $sequenceFlowsById.ContainsKey($lineId)) {
                    Add-ValidationError "Gateway line does not exist in processXml: $lineId"
                }
            }

            if ($node.nodeFormConf -and $data.formDef.id -and $node.nodeFormConf.mdlFormId -and
                ([string]$node.nodeFormConf.mdlFormId -ne [string]$data.formDef.id)) {
                Add-ValidationError "Form ID mismatch for node $nodeId."
            }
        }

        $fieldCodes = @{}
        foreach ($field in @($data.formDef.fieldList)) {
            $fieldCode = [string]$field.fieldCode
            if ($fieldCode) {
                $fieldCodes[$fieldCode] = $true
            }
        }

        foreach ($node in @($data.nodeConf)) {
            foreach ($group in @($node.nodeFormConf.actFormInfo.PSObject.Properties)) {
                foreach ($propertyName in @('requireGroup', 'disabledGroup', 'hideGroup')) {
                    $references = @($group.Value.$propertyName)
                    foreach ($fieldCode in $references) {
                        $fieldReference = [string]$fieldCode
                        $fieldBaseCode = $fieldReference.Split('|')[0]
                        if ($fieldReference -and -not $fieldCodes.ContainsKey($fieldReference) -and
                            -not $fieldCodes.ContainsKey($fieldBaseCode)) {
                            Add-ValidationError "Unknown form field '$fieldCode' in $propertyName for group '$($group.Name)'."
                        }
                    }
                }
            }
        }

        $tabIds = @{}
        foreach ($tab in @($data.tabConfig)) {
            $tabId = [string]$tab.id
            if ($tabId) {
                $tabIds[$tabId] = $true
            }
        }

        foreach ($node in @($data.nodeConf)) {
            foreach ($tabGroup in @($node.nodeFormConf.actTabGroupInfo)) {
                foreach ($tabId in @($tabGroup.tabIds)) {
                    if ($tabId -and -not $tabIds.ContainsKey([string]$tabId)) {
                        Add-ValidationError "Unknown Tab ID '$tabId' for node '$($node.actNodeId)'."
                    }
                }
            }
        }
    }
}

if ($errors.Count -gt 0) {
    Write-Error ("Process JSON validation failed:`n- " + ($errors -join "`n- "))
    exit 1
}

Write-Output "Process JSON validation passed: $Path"