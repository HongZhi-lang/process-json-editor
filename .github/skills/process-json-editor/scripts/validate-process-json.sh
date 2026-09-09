#!/bin/bash

set -euo pipefail

usage() {
  cat >&2 <<'EOF'
用法:
  ./validate-process-json.sh -p <流程JSON文件路径>

示例:
  chmod +x .github/skills/process-json-editor/scripts/validate-process-json.sh
  ./.github/skills/process-json-editor/scripts/validate-process-json.sh \
    -p test/process_main_test/PROC_c738b53a375d46d9b258c020d2a4720b.json
EOF
  exit 1
}

path=''

while getopts ':p:' option; do
  case "$option" in
    p) path="$OPTARG" ;;
    *) usage ;;
  esac
done

if [[ -z "$path" || ! -f "$path" ]]; then
  usage
fi

python3 - "$path" <<'PY'
import json
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence

path = sys.argv[1]
errors = []

def add_error(message: str) -> None:
    errors.append(message)

def flatten_field_references(value):
    refs = []
    if isinstance(value, dict):
        for key, val in value.items():
            if key in {'requireGroup', 'disabledGroup', 'hideGroup'} and isinstance(val, list):
                refs.extend(str(item) for item in val)
            else:
                refs.extend(flatten_field_references(val))
    elif isinstance(value, list):
        for item in value:
            refs.extend(flatten_field_references(item))
    return refs

try:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
except Exception as exc:
    add_error(f"JSON cannot be parsed: {exc}")
    data = None

if data is not None:
    if data.get('processInfo') is None:
        add_error('Missing processInfo.')

    process_info = data.get('processInfo') or {}
    process_xml = str(process_info.get('processXml', ''))
    try:
        root = ET.fromstring(process_xml)
    except Exception as exc:
        add_error(f"processInfo.processXml cannot be parsed: {exc}")
        root = None

    if root is not None:
        xml_nodes_by_id = {}
        for element in root.iter():
            element_id = element.get('id')
            if element_id:
                if element_id in xml_nodes_by_id:
                    add_error(f"Duplicate XML id: {element_id}")
                else:
                    xml_nodes_by_id[element_id] = element

        sequence_flows_by_id = {}
        for flow in root.findall('.//bpmn:sequenceFlow', {'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL'}):
            flow_id = flow.get('id')
            if flow_id:
                sequence_flows_by_id[flow_id] = flow

        for node in data.get('nodeConf') or []:
            node_id = str(node.get('actNodeId', ''))
            if not node_id:
                add_error('nodeConf contains an entry without actNodeId.')
                continue

            if node_id not in xml_nodes_by_id:
                add_error(f"nodeConf actNodeId does not exist in processXml: {node_id}")
                continue

            xml_node = xml_nodes_by_id[node_id]
            xml_name = str(xml_node.get('name', ''))
            if xml_name and str(node.get('actNodeName', '')) != xml_name:
                add_error(f"Node name mismatch for {node_id}: nodeConf='{node.get('actNodeName')}', XML='{xml_name}'")

            for apply in node.get('applyConf') or []:
                line_id = str(apply.get('actLineId', ''))
                if line_id and line_id not in sequence_flows_by_id:
                    add_error(f"Gateway line does not exist in processXml: {line_id}")

            node_form_conf = node.get('nodeFormConf') or {}
            form_id = data.get('formDef', {}).get('id')
            mdl_form_id = node_form_conf.get('mdlFormId')
            if node_form_conf and form_id and mdl_form_id and str(mdl_form_id) != str(form_id):
                add_error(f"Form ID mismatch for node {node_id}.")

        field_codes = {}
        for field in data.get('formDef', {}).get('fieldList') or []:
            field_code = str(field.get('fieldCode', ''))
            if field_code:
                field_codes[field_code] = True

        for node in data.get('nodeConf') or []:
            node_form_conf = node.get('nodeFormConf') or {}
            refs = flatten_field_references(node_form_conf.get('actFormInfo') or {})
            for field_code in refs:
                field_base_code = field_code.split('|')[0]
                if field_code and field_code not in field_codes and field_base_code not in field_codes:
                    add_error(f"Unknown form field '{field_code}' in nodeFormConf.actFormInfo for node '{node.get('actNodeId')}'.")

        tab_ids = {}
        for tab in data.get('tabConfig') or []:
            tab_id = str(tab.get('id', ''))
            if tab_id:
                tab_ids[tab_id] = True

        for node in data.get('nodeConf') or []:
            node_form_conf = node.get('nodeFormConf') or {}
            tab_groups = node_form_conf.get('actTabGroupInfo') or []
            if isinstance(tab_groups, dict):
                tab_groups = [tab_groups]
            for tab_group in tab_groups:
                tab_ids_list = tab_group.get('tabIds') if isinstance(tab_group, dict) else []
                for tab_id in tab_ids_list or []:
                    if tab_id and str(tab_id) not in tab_ids:
                        add_error(f"Unknown Tab ID '{tab_id}' for node '{node.get('actNodeId')}'.")

if errors:
    print('Process JSON validation failed:')
    for error in errors:
        print(f'- {error}')
    sys.exit(1)

print(f'Process JSON validation passed: {path}')
PY
