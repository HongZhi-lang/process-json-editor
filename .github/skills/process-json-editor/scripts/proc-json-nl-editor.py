#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr


PROC_FILE_PATTERN = re.compile(r"^PROC_.*\.json$")
BPMN_NS = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}
ACTION_PATTERN = r"\s*(?:改为|修改为|设为|设置为|重命名为)\s*"
PROTECTED_PATH_PATTERNS = [
    re.compile(r"^/processInfo/processXml$"),
    re.compile(r"^/processInfo/mdlFormId$"),
    re.compile(r"^/formDef/id$"),
    re.compile(r"^/firstNodeId$"),
    re.compile(r"^/nodeConf/\d+/actNodeId$"),
    re.compile(r"^/nodeConf/\d+/applyConf/\d+/actLineId$"),
    re.compile(r"^/nodeConf/\d+/nodeFormConf/mdlFormId$"),
    re.compile(r"^/tabConfig/\d+/id$"),
    re.compile(r"^/formDef/fieldList/\d+/fieldCode$"),
]


class ProcJsonEditorError(RuntimeError):
    pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PROC_*.json natural-language editing helper."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    summarize_parser = subparsers.add_parser(
        "summarize", help="Summarize a PROC_*.json file without printing the full JSON."
    )
    add_target_arguments(summarize_parser)
    summarize_parser.add_argument("--limit", type=int, default=8)

    find_parser = subparsers.add_parser(
        "find", help="Find candidate JSON pointers for a natural-language query."
    )
    add_target_arguments(find_parser)
    find_parser.add_argument("--query", required=True)
    find_parser.add_argument("--limit", type=int, default=10)

    slice_parser = subparsers.add_parser(
        "slice", help="Print a local JSON slice plus one-hop related references."
    )
    add_target_arguments(slice_parser)
    slice_parser.add_argument("--pointer", required=True)
    slice_parser.add_argument("--max-related", type=int, default=8)

    apply_parser = subparsers.add_parser(
        "apply",
        help="Apply structured path-based edits to a PROC_*.json file.",
    )
    add_target_arguments(apply_parser)
    apply_parser.add_argument("--ops-file", required=True)
    apply_parser.add_argument("--dry-run", action="store_true")

    edit_parser = subparsers.add_parser(
        "edit",
        help="Apply a supported natural-language edit directly.",
    )
    add_target_arguments(edit_parser)
    edit_parser.add_argument("--request", required=True)
    edit_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    try:
        proc_path = resolve_proc_target(args.target)

        if args.command == "summarize":
            data = load_json(proc_path)
            print_json(build_summary(proc_path, data, args.limit))
            return 0

        if args.command == "find":
            data = load_json(proc_path)
            index = build_search_index(data)
            result = {
                "path": str(proc_path),
                "query": args.query,
                "candidates": find_candidates(index, args.query, args.limit),
            }
            print_json(result)
            return 0

        if args.command == "slice":
            data = load_json(proc_path)
            print_json(build_slice_context(proc_path, data, args.pointer, args.max_related))
            return 0

        if args.command == "apply":
            data = load_json(proc_path)
            operations = load_operations(Path(args.ops_file))
            result = apply_operations_to_file(
                proc_path=proc_path,
                data=data,
                operations=operations,
                dry_run=args.dry_run,
                source="structured-ops",
            )
            print_json(result)
            return 0

        if args.command == "edit":
            data = load_json(proc_path)
            operations = parse_request_to_operations(args.request)
            result = apply_operations_to_file(
                proc_path=proc_path,
                data=data,
                operations=operations,
                dry_run=args.dry_run,
                source=args.request,
            )
            result["request"] = args.request
            print_json(result)
            return 0

        raise ProcJsonEditorError(f"Unsupported command: {args.command}")
    except ProcJsonEditorError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


def add_target_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--target",
        required=True,
        help="PROC_*.json file path, or a process_main_* directory that contains one PROC_*.json file.",
    )


def resolve_proc_target(target: str) -> Path:
    path = Path(target).expanduser().resolve()
    if not path.exists():
        raise ProcJsonEditorError(f"Target does not exist: {target}")

    if path.is_file():
        if not PROC_FILE_PATTERN.match(path.name):
            raise ProcJsonEditorError(
                f"Target file is not a PROC_*.json file: {path.name}"
            )
        return path

    matches = sorted(candidate for candidate in path.rglob("PROC_*.json") if candidate.is_file())
    if not matches:
        raise ProcJsonEditorError(f"No PROC_*.json file found under: {path}")
    if len(matches) > 1:
        match_list = ", ".join(str(item) for item in matches[:5])
        raise ProcJsonEditorError(
            f"More than one PROC_*.json file found under {path}. "
            f"Please pass the exact file path. Candidates: {match_list}"
        )
    return matches[0]


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:  # pragma: no cover - exercised by CLI failure paths
        raise ProcJsonEditorError(f"JSON cannot be parsed: {exc}") from exc


def write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_summary(path: Path, data: dict[str, Any], limit: int) -> dict[str, Any]:
    process_info = data.get("processInfo") or {}
    node_conf = data.get("nodeConf") or []
    field_list = data.get("formDef", {}).get("fieldList") or []
    tab_config = data.get("tabConfig") or []
    return {
        "path": str(path),
        "processName": process_info.get("processName"),
        "counts": {
            "nodes": len(node_conf),
            "fields": len(field_list),
            "tabs": len(tab_config),
        },
        "nodes": [
            {
                "pointer": f"/nodeConf/{index}",
                "actNodeId": node.get("actNodeId"),
                "actNodeName": node.get("actNodeName"),
                "actNodeType": node.get("actNodeType"),
            }
            for index, node in list(enumerate(node_conf))[:limit]
        ],
        "fields": [
            {
                "pointer": f"/formDef/fieldList/{index}",
                "fieldCode": field.get("fieldCode"),
                "fieldName": field.get("fieldName"),
                "fieldType": field.get("fieldType"),
            }
            for index, field in list(enumerate(field_list))[:limit]
        ],
        "tabs": [
            {
                "pointer": f"/tabConfig/{index}",
                "id": tab.get("id"),
                "tabName": tab.get("tabName"),
                "tabAlias": tab.get("tabAlias"),
            }
            for index, tab in list(enumerate(tab_config))[:limit]
        ],
    }


def build_search_index(data: dict[str, Any]) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = []
    process_info = data.get("processInfo") or {}
    form_def = data.get("formDef") or {}
    form_info = form_def.get("formInfo") or {}
    form_info_paths = collect_form_info_paths(form_info)
    field_permission_refs = collect_node_field_reference_paths(data.get("nodeConf") or [])
    tab_refs = collect_node_tab_reference_paths(data.get("nodeConf") or [])

    index.append(
        make_index_entry(
            pointer="/processInfo",
            kind="process",
            identifiers=[process_info.get("id"), process_info.get("processName")],
            summary=f"流程 {process_info.get('processName') or ''}".strip(),
        )
    )

    for node_index, node in enumerate(data.get("nodeConf") or []):
        base_pointer = f"/nodeConf/{node_index}"
        index.append(
            make_index_entry(
                pointer=base_pointer,
                kind="node",
                identifiers=[
                    node.get("actNodeId"),
                    node.get("actNodeName"),
                    node.get("actNodeType"),
                ],
                summary=(
                    f"节点 {node.get('actNodeName') or ''} "
                    f"({node.get('actNodeId') or ''}) {node.get('actNodeType') or ''}"
                ).strip(),
            )
        )
        if node.get("handlerConf"):
            index.append(
                make_index_entry(
                    pointer=f"{base_pointer}/handlerConf",
                    kind="node-handler",
                    identifiers=[node.get("actNodeId"), node.get("actNodeName")],
                    summary=f"{node.get('actNodeName') or node.get('actNodeId') or ''} 的处理人配置",
                )
            )
        if node.get("nodeFormConf"):
            index.append(
                make_index_entry(
                    pointer=f"{base_pointer}/nodeFormConf",
                    kind="node-form",
                    identifiers=[node.get("actNodeId"), node.get("actNodeName")],
                    summary=f"{node.get('actNodeName') or node.get('actNodeId') or ''} 的节点表单配置",
                )
            )
        if node.get("applyConf"):
            index.append(
                make_index_entry(
                    pointer=f"{base_pointer}/applyConf",
                    kind="gateway-conditions",
                    identifiers=[node.get("actNodeId"), node.get("actNodeName")],
                    summary=f"{node.get('actNodeName') or node.get('actNodeId') or ''} 的网关条件",
                )
            )

    for field_index, field in enumerate(form_def.get("fieldList") or []):
        field_code = str(field.get("fieldCode") or "")
        related_pointers = form_info_paths.get(field_code, [])[:5]
        related_pointers.extend(field_permission_refs.get(field_code, [])[:5])
        index.append(
            make_index_entry(
                pointer=f"/formDef/fieldList/{field_index}",
                kind="field",
                identifiers=[
                    field.get("fieldCode"),
                    field.get("fieldName"),
                    field.get("fieldType"),
                ],
                summary=(
                    f"字段 {field.get('fieldName') or ''} "
                    f"({field.get('fieldCode') or ''}) {field.get('fieldType') or ''}"
                ).strip(),
                related_pointers=related_pointers,
            )
        )

    for tab_index, tab in enumerate(data.get("tabConfig") or []):
        tab_id = str(tab.get("id") or "")
        index.append(
            make_index_entry(
                pointer=f"/tabConfig/{tab_index}",
                kind="tab",
                identifiers=[tab_id, tab.get("tabName"), tab.get("tabAlias")],
                summary=f"标签页 {tab.get('tabName') or ''} ({tab_id})".strip(),
                related_pointers=tab_refs.get(tab_id, [])[:5],
            )
        )

    return index


def make_index_entry(
    *,
    pointer: str,
    kind: str,
    identifiers: list[Any],
    summary: str,
    related_pointers: list[str] | None = None,
) -> dict[str, Any]:
    clean_identifiers = [str(item) for item in identifiers if item not in (None, "")]
    return {
        "pointer": pointer,
        "kind": kind,
        "identifiers": clean_identifiers,
        "summary": summary,
        "relatedPointers": dedupe_preserve_order(related_pointers or []),
    }


def collect_form_info_paths(form_info: Any) -> dict[str, list[str]]:
    paths: dict[str, list[str]] = {}

    def walk(node: Any, pointer: str) -> None:
        if isinstance(node, dict):
            x_props = node.get("x-props")
            if isinstance(x_props, dict):
                field_code = str(x_props.get("fieldCode") or "")
                if field_code:
                    paths.setdefault(field_code, []).append(pointer or "/")
            for key, value in node.items():
                walk(value, f"{pointer}/{escape_pointer_part(str(key))}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{pointer}/{index}")

    walk(form_info, "")
    return paths


def collect_node_field_reference_paths(node_conf: list[dict[str, Any]]) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}

    def walk(node: Any, pointer: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                next_pointer = f"{pointer}/{escape_pointer_part(str(key))}"
                if key in {"requireGroup", "disabledGroup", "hideGroup"} and isinstance(value, list):
                    for index, item in enumerate(value):
                        field_code = str(item)
                        refs.setdefault(field_code, []).append(f"{next_pointer}/{index}")
                else:
                    walk(value, next_pointer)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{pointer}/{index}")

    for node_index, node in enumerate(node_conf):
        walk(node.get("nodeFormConf") or {}, f"/nodeConf/{node_index}/nodeFormConf")
    return refs


def collect_node_tab_reference_paths(node_conf: list[dict[str, Any]]) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    for node_index, node in enumerate(node_conf):
        node_form_conf = node.get("nodeFormConf") or {}
        tab_groups = node_form_conf.get("actTabGroupInfo") or []
        if isinstance(tab_groups, dict):
            tab_groups = [tab_groups]
        for group_index, tab_group in enumerate(tab_groups):
            if not isinstance(tab_group, dict):
                continue
            for tab_index, tab_id in enumerate(tab_group.get("tabIds") or []):
                refs.setdefault(str(tab_id), []).append(
                    f"/nodeConf/{node_index}/nodeFormConf/actTabGroupInfo/{group_index}/tabIds/{tab_index}"
                )
    return refs


def find_candidates(
    index: list[dict[str, Any]], query: str, limit: int
) -> list[dict[str, Any]]:
    normalized_query = normalize_text(query)
    query_tokens = tokenize(query)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for entry in index:
        score = score_entry(entry, normalized_query, query_tokens)
        if score <= 0:
            continue
        ranked.append((score, entry))

    ranked.sort(
        key=lambda item: (
            -item[0],
            item[1]["kind"],
            item[1]["pointer"],
        )
    )
    return [
        {
            "pointer": entry["pointer"],
            "kind": entry["kind"],
            "score": score,
            "identifiers": entry["identifiers"],
            "summary": entry["summary"],
            "relatedPointers": entry["relatedPointers"],
        }
        for score, entry in ranked[:limit]
    ]


def score_entry(entry: dict[str, Any], normalized_query: str, query_tokens: list[str]) -> int:
    searchable_text = normalize_text(
        " ".join(
            [
                entry.get("pointer", ""),
                entry.get("kind", ""),
                entry.get("summary", ""),
                " ".join(entry.get("identifiers") or []),
                " ".join(entry.get("relatedPointers") or []),
            ]
        )
    )
    identifiers_text = normalize_text(" ".join(entry.get("identifiers") or []))

    score = 0
    if normalized_query and normalized_query in searchable_text:
        score += 10

    matched_tokens = 0
    for token in query_tokens:
        if token in identifiers_text:
            score += 6
            matched_tokens += 1
        elif token in searchable_text:
            score += 3
            matched_tokens += 1

    if query_tokens and matched_tokens == len(query_tokens):
        score += 4
    return score


def build_slice_context(
    path: Path, data: dict[str, Any], pointer: str, max_related: int
) -> dict[str, Any]:
    value = get_value_at_pointer(data, pointer)
    context: dict[str, Any] = {
        "path": str(path),
        "pointer": pointer,
        "value": trim_large_content(value),
        "related": {},
    }
    node_match = re.match(r"^/nodeConf/(\d+)(?:/.*)?$", pointer)
    field_match = re.match(r"^/formDef/fieldList/(\d+)(?:/.*)?$", pointer)
    tab_match = re.match(r"^/tabConfig/(\d+)(?:/.*)?$", pointer)

    if node_match:
        node_index = int(node_match.group(1))
        context["related"] = build_node_related_context(data, node_index, max_related)
    elif field_match:
        field_index = int(field_match.group(1))
        context["related"] = build_field_related_context(data, field_index, max_related)
    elif tab_match:
        tab_index = int(tab_match.group(1))
        context["related"] = build_tab_related_context(data, tab_index, max_related)

    return context


def build_node_related_context(
    data: dict[str, Any], node_index: int, max_related: int
) -> dict[str, Any]:
    node = (data.get("nodeConf") or [])[node_index]
    xml_meta = build_xml_metadata(str((data.get("processInfo") or {}).get("processXml") or ""))
    node_id = str(node.get("actNodeId") or "")
    xml_node = xml_meta["nodesById"].get(node_id)
    related = {
        "xmlNode": summarize_xml_element(xml_node),
        "incomingFlows": xml_meta["incoming"].get(node_id, [])[:max_related],
        "outgoingFlows": xml_meta["outgoing"].get(node_id, [])[:max_related],
    }
    if node.get("applyConf"):
        line_summaries = []
        for apply in node.get("applyConf") or []:
            flow = xml_meta["flowsById"].get(str(apply.get("actLineId") or ""))
            line_summaries.append(
                {
                    "actLineId": apply.get("actLineId"),
                    "actLineName": apply.get("actLineName"),
                    "condition": trim_large_content(apply.get("condition")),
                    "xmlFlow": flow,
                }
            )
        related["applyConf"] = line_summaries[:max_related]
    return related


def build_field_related_context(
    data: dict[str, Any], field_index: int, max_related: int
) -> dict[str, Any]:
    field = (data.get("formDef", {}).get("fieldList") or [])[field_index]
    field_code = str(field.get("fieldCode") or "")
    form_info_paths = collect_form_info_paths(data.get("formDef", {}).get("formInfo") or {})
    field_refs = collect_node_field_reference_paths(data.get("nodeConf") or [])
    return {
        "formInfoPointers": form_info_paths.get(field_code, [])[:max_related],
        "nodeFieldReferencePointers": field_refs.get(field_code, [])[:max_related],
    }


def build_tab_related_context(
    data: dict[str, Any], tab_index: int, max_related: int
) -> dict[str, Any]:
    tab = (data.get("tabConfig") or [])[tab_index]
    tab_id = str(tab.get("id") or "")
    tab_refs = collect_node_tab_reference_paths(data.get("nodeConf") or [])
    return {
        "nodeTabReferencePointers": tab_refs.get(tab_id, [])[:max_related],
    }


def build_xml_metadata(process_xml: str) -> dict[str, Any]:
    root = ET.fromstring(process_xml)
    nodes_by_id: dict[str, ET.Element] = {}
    flows_by_id: dict[str, dict[str, Any]] = {}
    incoming: dict[str, list[dict[str, Any]]] = {}
    outgoing: dict[str, list[dict[str, Any]]] = {}

    for element in root.iter():
        element_id = element.get("id")
        if element_id:
            nodes_by_id[element_id] = element

    for flow in root.findall(".//bpmn:sequenceFlow", BPMN_NS):
        flow_id = str(flow.get("id") or "")
        if not flow_id:
            continue
        flow_summary = {
            "id": flow_id,
            "name": flow.get("name"),
            "sourceRef": flow.get("sourceRef"),
            "targetRef": flow.get("targetRef"),
            "conditionExpression": extract_condition_expression(flow),
        }
        flows_by_id[flow_id] = flow_summary
        source_ref = str(flow.get("sourceRef") or "")
        target_ref = str(flow.get("targetRef") or "")
        if source_ref:
            outgoing.setdefault(source_ref, []).append(flow_summary)
        if target_ref:
            incoming.setdefault(target_ref, []).append(flow_summary)

    return {
        "nodesById": nodes_by_id,
        "flowsById": flows_by_id,
        "incoming": incoming,
        "outgoing": outgoing,
    }


def summarize_xml_element(element: ET.Element | None) -> dict[str, Any] | None:
    if element is None:
        return None
    return {
        "id": element.get("id"),
        "name": element.get("name"),
        "tag": local_name(element.tag),
    }


def extract_condition_expression(flow: ET.Element) -> str | None:
    for child in list(flow):
        if local_name(child.tag) == "conditionExpression":
            return (child.text or "").strip()
    return None


def local_name(tag: str) -> str:
    if "}" not in tag:
        return tag
    return tag.split("}", 1)[1]


def trim_large_content(value: Any, *, string_limit: int = 500, list_limit: int = 20) -> Any:
    if isinstance(value, str):
        if len(value) <= string_limit:
            return value
        return f"{value[:string_limit]} …(trimmed, total {len(value)} chars)"
    if isinstance(value, list):
        trimmed = [trim_large_content(item, string_limit=string_limit, list_limit=list_limit) for item in value[:list_limit]]
        if len(value) > list_limit:
            trimmed.append(f"... {len(value) - list_limit} more item(s)")
        return trimmed
    if isinstance(value, dict):
        return {
            key: trim_large_content(item, string_limit=string_limit, list_limit=list_limit)
            for key, item in value.items()
        }
    return value


def load_operations(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        raise ProcJsonEditorError(f"Cannot read operations file {path}: {exc}") from exc

    if isinstance(payload, list):
        operations = payload
    elif isinstance(payload, dict) and isinstance(payload.get("operations"), list):
        operations = payload["operations"]
    else:
        raise ProcJsonEditorError(
            "Operations file must contain a JSON array or an object with an 'operations' array."
        )

    if not operations:
        raise ProcJsonEditorError("Operations file is empty.")
    return operations


def apply_operations_to_file(
    *,
    proc_path: Path,
    data: dict[str, Any],
    operations: list[dict[str, Any]],
    dry_run: bool,
    source: str,
) -> dict[str, Any]:
    updated = copy.deepcopy(data)
    applied: list[dict[str, Any]] = []

    for operation in operations:
        applied.append(apply_operation(updated, operation))

    errors = validate_process_json_data(updated)
    if errors:
        raise ProcJsonEditorError(
            "Validation failed after applying edits:\n- " + "\n- ".join(errors)
        )

    if not dry_run:
        write_json(proc_path, updated)

    return {
        "path": str(proc_path),
        "changed": not dry_run,
        "dryRun": dry_run,
        "source": source,
        "appliedOperations": applied,
        "validation": {"passed": True},
    }


def apply_operation(data: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    op_type = str(operation.get("op") or "").strip()
    if not op_type:
        raise ProcJsonEditorError("Operation is missing the 'op' field.")

    if op_type == "replace":
        path = require_operation_path(operation)
        ensure_path_is_safe(path)
        set_value_at_pointer(data, path, operation.get("value"))
        return {"op": "replace", "path": path}

    if op_type == "merge":
        path = require_operation_path(operation)
        ensure_path_is_safe(path)
        value = operation.get("value")
        if not isinstance(value, dict):
            raise ProcJsonEditorError("merge operation requires an object 'value'.")
        current = get_value_at_pointer(data, path)
        if not isinstance(current, dict):
            raise ProcJsonEditorError(f"merge target is not an object: {path}")
        deep_merge(current, value)
        return {"op": "merge", "path": path}

    if op_type == "append":
        path = require_operation_path(operation)
        ensure_path_is_safe(path)
        current = get_value_at_pointer(data, path)
        if not isinstance(current, list):
            raise ProcJsonEditorError(f"append target is not an array: {path}")
        current.append(operation.get("value"))
        return {"op": "append", "path": path}

    if op_type == "remove":
        path = require_operation_path(operation)
        ensure_path_is_safe(path)
        remove_value_at_pointer(data, path)
        return {"op": "remove", "path": path}

    if op_type == "rename_node":
        return apply_rename_node(data, operation)

    if op_type == "update_field":
        return apply_update_field(data, operation)

    if op_type == "update_tab":
        return apply_update_tab(data, operation)

    raise ProcJsonEditorError(f"Unsupported operation type: {op_type}")


def require_operation_path(operation: dict[str, Any]) -> str:
    path = str(operation.get("path") or "")
    if not path:
        raise ProcJsonEditorError(f"Operation is missing path: {operation}")
    return path


def ensure_path_is_safe(path: str) -> None:
    for pattern in PROTECTED_PATH_PATTERNS:
        if pattern.match(path):
            raise ProcJsonEditorError(
                f"Protected path requires a dedicated sync-aware operation and cannot be changed directly: {path}"
            )


def apply_rename_node(data: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    match = operation.get("match")
    if not isinstance(match, dict):
        raise ProcJsonEditorError("rename_node operation requires an object 'match'.")
    new_name = clean_capture(str(operation.get("newName") or ""))
    if not new_name:
        raise ProcJsonEditorError("rename_node operation requires 'newName'.")

    node_index, node = find_unique_node(data, match)
    node_id = str(node.get("actNodeId") or "")
    node["actNodeName"] = new_name

    process_info = data.get("processInfo") or {}
    process_xml = str(process_info.get("processXml") or "")
    xml_meta = build_xml_metadata(process_xml)
    if node_id not in xml_meta["nodesById"]:
        raise ProcJsonEditorError(f"Cannot find node {node_id} in processXml.")
    data["processInfo"]["processXml"] = replace_xml_node_name(process_xml, node_id, new_name)

    return {
        "op": "rename_node",
        "pointer": f"/nodeConf/{node_index}",
        "actNodeId": node_id,
        "newName": new_name,
    }


def replace_xml_node_name(process_xml: str, node_id: str, new_name: str) -> str:
    tag_pattern = re.compile(
        rf"<(?P<tag>[^\s>/][^>]*)\bid=\"{re.escape(node_id)}\"(?P<attrs>[^>]*)>",
        re.DOTALL,
    )
    match = tag_pattern.search(process_xml)
    if not match:
        raise ProcJsonEditorError(f"Cannot locate XML element with id '{node_id}'.")

    full_tag = match.group(0)
    escaped_name = quoteattr(new_name)
    if re.search(r'\bname="[^"]*"', full_tag):
        updated_tag = re.sub(r'\bname="[^"]*"', f"name={escaped_name}", full_tag, count=1)
    else:
        if full_tag.endswith("/>"):
            updated_tag = f"{full_tag[:-2]} name={escaped_name}/>"
        else:
            updated_tag = f"{full_tag[:-1]} name={escaped_name}>"
    return process_xml[: match.start()] + updated_tag + process_xml[match.end() :]


def apply_update_field(data: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    match = operation.get("match")
    changes = operation.get("changes")
    if not isinstance(match, dict) or not isinstance(changes, dict):
        raise ProcJsonEditorError("update_field requires 'match' and 'changes' objects.")

    field_index, field = find_unique_field(data, match)
    field_code = str(field.get("fieldCode") or "")
    form_nodes = find_form_info_nodes_by_field_code(data.get("formDef", {}).get("formInfo") or {}, field_code)

    supported_changes = set(changes)
    unsupported = supported_changes - {"fieldName", "defaultValue"}
    if unsupported:
        raise ProcJsonEditorError(
            "update_field only supports fieldName and defaultValue in this MVP. "
            f"Unsupported keys: {sorted(unsupported)}"
        )

    if "fieldName" in changes:
        field["fieldName"] = changes["fieldName"]
        for _, form_node in form_nodes:
            if isinstance(form_node, dict) and "title" in form_node:
                form_node["title"] = changes["fieldName"]

    if "defaultValue" in changes:
        field["defaultValue"] = changes["defaultValue"]
        for _, form_node in form_nodes:
            if not isinstance(form_node, dict):
                continue
            form_node["default"] = changes["defaultValue"]
            x_props = form_node.get("x-props")
            if isinstance(x_props, dict):
                x_props["defaultValue"] = changes["defaultValue"]

    return {
        "op": "update_field",
        "pointer": f"/formDef/fieldList/{field_index}",
        "fieldCode": field_code,
        "changes": changes,
    }


def apply_update_tab(data: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    match = operation.get("match")
    changes = operation.get("changes")
    if not isinstance(match, dict) or not isinstance(changes, dict):
        raise ProcJsonEditorError("update_tab requires 'match' and 'changes' objects.")

    supported_changes = set(changes)
    unsupported = supported_changes - {"tabName", "tabAlias"}
    if unsupported:
        raise ProcJsonEditorError(
            "update_tab only supports tabName and tabAlias in this MVP. "
            f"Unsupported keys: {sorted(unsupported)}"
        )

    tab_index, tab = find_unique_tab(data, match)
    for key in ("tabName", "tabAlias"):
        if key in changes:
            tab[key] = changes[key]

    return {
        "op": "update_tab",
        "pointer": f"/tabConfig/{tab_index}",
        "tabId": tab.get("id"),
        "changes": changes,
    }


def find_unique_node(data: dict[str, Any], match: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    node_conf = data.get("nodeConf") or []
    target_id = str(match.get("actNodeId") or "")
    target_name = str(match.get("actNodeName") or "")
    matches = []
    for index, node in enumerate(node_conf):
        if target_id and str(node.get("actNodeId") or "") == target_id:
            matches.append((index, node))
        elif target_name and str(node.get("actNodeName") or "") == target_name:
            matches.append((index, node))
    if not matches:
        raise ProcJsonEditorError(f"Cannot find node with selector: {match}")
    if len(matches) > 1:
        raise ProcJsonEditorError(f"Node selector is ambiguous: {match}")
    return matches[0]


def find_unique_field(data: dict[str, Any], match: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    fields = data.get("formDef", {}).get("fieldList") or []
    target_code = str(match.get("fieldCode") or "")
    target_name = str(match.get("fieldName") or "")
    matches = []
    for index, field in enumerate(fields):
        if target_code and str(field.get("fieldCode") or "") == target_code:
            matches.append((index, field))
        elif target_name and str(field.get("fieldName") or "") == target_name:
            matches.append((index, field))
    if not matches:
        raise ProcJsonEditorError(f"Cannot find field with selector: {match}")
    if len(matches) > 1:
        raise ProcJsonEditorError(f"Field selector is ambiguous: {match}")
    return matches[0]


def find_unique_tab(data: dict[str, Any], match: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    tabs = data.get("tabConfig") or []
    target_id = str(match.get("id") or "")
    target_name = str(match.get("tabName") or "")
    target_alias = str(match.get("tabAlias") or "")
    matches = []
    for index, tab in enumerate(tabs):
        if target_id and str(tab.get("id") or "") == target_id:
            matches.append((index, tab))
        elif target_name and str(tab.get("tabName") or "") == target_name:
            matches.append((index, tab))
        elif target_alias and str(tab.get("tabAlias") or "") == target_alias:
            matches.append((index, tab))
    if not matches:
        raise ProcJsonEditorError(f"Cannot find tab with selector: {match}")
    if len(matches) > 1:
        raise ProcJsonEditorError(f"Tab selector is ambiguous: {match}")
    return matches[0]


def find_form_info_nodes_by_field_code(form_info: Any, field_code: str) -> list[tuple[str, dict[str, Any]]]:
    matches: list[tuple[str, dict[str, Any]]] = []

    def walk(node: Any, pointer: str) -> None:
        if isinstance(node, dict):
            x_props = node.get("x-props")
            if isinstance(x_props, dict) and str(x_props.get("fieldCode") or "") == field_code:
                matches.append((pointer or "/", node))
            for key, value in node.items():
                walk(value, f"{pointer}/{escape_pointer_part(str(key))}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{pointer}/{index}")

    walk(form_info, "")
    return matches


def parse_request_to_operations(request: str) -> list[dict[str, Any]]:
    normalized = request.strip()
    if not normalized:
        raise ProcJsonEditorError("Request is empty.")

    patterns: list[tuple[re.Pattern[str], Any]] = [
        (
            re.compile(rf"^(?:把|将)?流程(?:名称|名字)?{ACTION_PATTERN}(?P<value>.+)$", re.IGNORECASE),
            parse_process_rename,
        ),
        (
            re.compile(
                rf"^(?:把|将)?节点\s*(?P<target>.+?)(?:\s*节点)?(?:的)?(?:名称|名字)?{ACTION_PATTERN}(?P<value>.+)$",
                re.IGNORECASE,
            ),
            parse_node_rename,
        ),
        (
            re.compile(r"^rename node (?P<target>.+?) to (?P<value>.+)$", re.IGNORECASE),
            parse_node_rename,
        ),
        (
            re.compile(
                rf"^(?:把|将)?字段\s*(?P<target>.+?)(?:的)?(?P<prop>名称|名字|标题|默认值){ACTION_PATTERN}(?P<value>.+)$",
                re.IGNORECASE,
            ),
            parse_field_update,
        ),
        (
            re.compile(
                r"^(?:update|set) field (?P<target>.+?) (?P<prop>name|title|default value) to (?P<value>.+)$",
                re.IGNORECASE,
            ),
            parse_field_update,
        ),
        (
            re.compile(
                rf"^(?:把|将)?(?:标签页|tab)\s*(?P<target>.+?)(?:的)?(?P<prop>名称|名字|别名)?{ACTION_PATTERN}(?P<value>.+)$",
                re.IGNORECASE,
            ),
            parse_tab_update,
        ),
        (
            re.compile(
                r"^(?:rename|update) tab (?P<target>.+?)(?: (?P<prop>name|alias))? to (?P<value>.+)$",
                re.IGNORECASE,
            ),
            parse_tab_update,
        ),
    ]

    for pattern, parser in patterns:
        match = pattern.match(normalized)
        if match:
            return parser(match)

    raise ProcJsonEditorError(
        "Unsupported natural-language request for the MVP. "
        "Use summarize/find/slice to locate the JSON pointer, then use apply with structured operations."
    )


def parse_process_rename(match: re.Match[str]) -> list[dict[str, Any]]:
    return [
        {
            "op": "replace",
            "path": "/processInfo/processName",
            "value": clean_capture(match.group("value")),
        }
    ]


def parse_node_rename(match: re.Match[str]) -> list[dict[str, Any]]:
    target = clean_capture(match.group("target"))
    return [
        {
            "op": "rename_node",
            "match": {"actNodeId": target, "actNodeName": target},
            "newName": clean_capture(match.group("value")),
        }
    ]


def parse_field_update(match: re.Match[str]) -> list[dict[str, Any]]:
    target = clean_capture(match.group("target"))
    prop = normalize_text(match.group("prop"))
    if prop in {"名称", "名字", "title", "name"}:
        changes = {"fieldName": clean_capture(match.group("value"))}
    elif prop in {"默认值", "default value"}:
        changes = {"defaultValue": clean_capture(match.group("value"))}
    else:
        raise ProcJsonEditorError(f"Unsupported field property in MVP: {match.group('prop')}")
    return [
        {
            "op": "update_field",
            "match": {"fieldCode": target, "fieldName": target},
            "changes": changes,
        }
    ]


def parse_tab_update(match: re.Match[str]) -> list[dict[str, Any]]:
    target = clean_capture(match.group("target"))
    prop = normalize_text(match.groupdict().get("prop") or "")
    if prop in {"", "名称", "名字", "name"}:
        new_value = clean_capture(match.group("value"))
        return [
            {
                "op": "update_tab",
                "match": {"id": target, "tabName": target, "tabAlias": target},
                "changes": {"tabName": new_value, "tabAlias": new_value},
            }
        ]
    if prop in {"别名", "alias"}:
        return [
            {
                "op": "update_tab",
                "match": {"id": target, "tabName": target, "tabAlias": target},
                "changes": {"tabAlias": clean_capture(match.group("value"))},
            }
        ]
    raise ProcJsonEditorError(f"Unsupported tab property in MVP: {match.group('prop')}")


def clean_capture(value: str) -> str:
    cleaned = value.strip()
    while len(cleaned) >= 2 and cleaned[0] in "\"'“‘" and cleaned[-1] in "\"'”’":
        cleaned = cleaned[1:-1].strip()
    return cleaned


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def tokenize(value: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", value)]


def escape_pointer_part(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def split_pointer(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ProcJsonEditorError(f"Invalid JSON pointer: {pointer}")
    if pointer == "/":
        return [""]
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def get_value_at_pointer(data: Any, pointer: str) -> Any:
    current = data
    for part in split_pointer(pointer):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise ProcJsonEditorError(f"List path does not exist: {pointer}") from exc
        elif isinstance(current, dict):
            if part not in current:
                raise ProcJsonEditorError(f"Object path does not exist: {pointer}")
            current = current[part]
        else:
            raise ProcJsonEditorError(f"Path does not exist: {pointer}")
    return current


def set_value_at_pointer(data: Any, pointer: str, value: Any) -> None:
    parent, last_part = get_parent_and_last_part(data, pointer)
    if isinstance(parent, list):
        try:
            parent[int(last_part)] = value
        except (ValueError, IndexError) as exc:
            raise ProcJsonEditorError(f"List path does not exist: {pointer}") from exc
    elif isinstance(parent, dict):
        parent[last_part] = value
    else:
        raise ProcJsonEditorError(f"Cannot set path: {pointer}")


def remove_value_at_pointer(data: Any, pointer: str) -> None:
    parent, last_part = get_parent_and_last_part(data, pointer)
    if isinstance(parent, list):
        try:
            del parent[int(last_part)]
        except (ValueError, IndexError) as exc:
            raise ProcJsonEditorError(f"List path does not exist: {pointer}") from exc
    elif isinstance(parent, dict):
        if last_part not in parent:
            raise ProcJsonEditorError(f"Object path does not exist: {pointer}")
        del parent[last_part]
    else:
        raise ProcJsonEditorError(f"Cannot remove path: {pointer}")


def get_parent_and_last_part(data: Any, pointer: str) -> tuple[Any, str]:
    parts = split_pointer(pointer)
    if not parts:
        raise ProcJsonEditorError("Editing the JSON document root is not supported.")
    current = data
    for part in parts[:-1]:
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise ProcJsonEditorError(f"List path does not exist: {pointer}") from exc
        elif isinstance(current, dict):
            if part not in current:
                raise ProcJsonEditorError(f"Object path does not exist: {pointer}")
            current = current[part]
        else:
            raise ProcJsonEditorError(f"Path does not exist: {pointer}")
    return current, parts[-1]


def deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = value


def flatten_field_references(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"requireGroup", "disabledGroup", "hideGroup"} and isinstance(nested, list):
                refs.extend(str(item) for item in nested)
            else:
                refs.extend(flatten_field_references(nested))
    elif isinstance(value, list):
        for item in value:
            refs.extend(flatten_field_references(item))
    return refs


def validate_process_json_data(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    def add_error(message: str) -> None:
        errors.append(message)

    if data.get("processInfo") is None:
        add_error("Missing processInfo.")

    process_info = data.get("processInfo") or {}
    process_xml = str(process_info.get("processXml", ""))
    try:
        root = ET.fromstring(process_xml)
    except Exception as exc:
        add_error(f"processInfo.processXml cannot be parsed: {exc}")
        root = None

    if root is not None:
        xml_nodes_by_id: dict[str, ET.Element] = {}
        for element in root.iter():
            element_id = element.get("id")
            if element_id:
                if element_id in xml_nodes_by_id:
                    add_error(f"Duplicate XML id: {element_id}")
                else:
                    xml_nodes_by_id[element_id] = element

        sequence_flows_by_id: dict[str, ET.Element] = {}
        for flow in root.findall(".//bpmn:sequenceFlow", BPMN_NS):
            flow_id = flow.get("id")
            if flow_id:
                sequence_flows_by_id[flow_id] = flow

        for node in data.get("nodeConf") or []:
            node_id = str(node.get("actNodeId", ""))
            if not node_id:
                add_error("nodeConf contains an entry without actNodeId.")
                continue

            if node_id not in xml_nodes_by_id:
                add_error(f"nodeConf actNodeId does not exist in processXml: {node_id}")
                continue

            xml_node = xml_nodes_by_id[node_id]
            xml_name = str(xml_node.get("name", ""))
            if xml_name and str(node.get("actNodeName", "")) != xml_name:
                add_error(
                    f"Node name mismatch for {node_id}: "
                    f"nodeConf='{node.get('actNodeName')}', XML='{xml_name}'"
                )

            for apply in node.get("applyConf") or []:
                line_id = str(apply.get("actLineId", ""))
                if line_id and line_id not in sequence_flows_by_id:
                    add_error(f"Gateway line does not exist in processXml: {line_id}")

            node_form_conf = node.get("nodeFormConf") or {}
            form_id = data.get("formDef", {}).get("id")
            mdl_form_id = node_form_conf.get("mdlFormId")
            if node_form_conf and form_id and mdl_form_id and str(mdl_form_id) != str(form_id):
                add_error(f"Form ID mismatch for node {node_id}.")

    field_codes: dict[str, bool] = {}
    for field in data.get("formDef", {}).get("fieldList") or []:
        field_code = str(field.get("fieldCode", ""))
        if field_code:
            field_codes[field_code] = True

    for node in data.get("nodeConf") or []:
        node_form_conf = node.get("nodeFormConf") or {}
        refs = flatten_field_references(node_form_conf.get("actFormInfo") or {})
        for field_code in refs:
            field_base_code = field_code.split("|")[0]
            if field_code and field_code not in field_codes and field_base_code not in field_codes:
                add_error(
                    f"Unknown form field '{field_code}' in nodeFormConf.actFormInfo "
                    f"for node '{node.get('actNodeId')}'."
                )

    tab_ids: dict[str, bool] = {}
    for tab in data.get("tabConfig") or []:
        tab_id = str(tab.get("id", ""))
        if tab_id:
            tab_ids[tab_id] = True

    for node in data.get("nodeConf") or []:
        node_form_conf = node.get("nodeFormConf") or {}
        tab_groups = node_form_conf.get("actTabGroupInfo") or []
        if isinstance(tab_groups, dict):
            tab_groups = [tab_groups]
        for tab_group in tab_groups:
            tab_ids_list = tab_group.get("tabIds") if isinstance(tab_group, dict) else []
            for tab_id in tab_ids_list or []:
                if tab_id and str(tab_id) not in tab_ids:
                    add_error(f"Unknown Tab ID '{tab_id}' for node '{node.get('actNodeId')}'.")

    return errors


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


if __name__ == "__main__":
    sys.exit(main())
