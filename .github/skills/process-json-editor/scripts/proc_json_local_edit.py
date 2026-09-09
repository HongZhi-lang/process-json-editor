#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

JSONValue = Any

COMMON_REFERENCE_KEYS = {
    "id",
    "ref",
    "key",
    "name",
    "target",
    "source",
    "component",
    "action",
}

PROC_REFERENCE_KEYS = {
    "actNodeId",
    "actLineId",
    "sourceRef",
    "targetRef",
    "firstNodeId",
    "mdlFormId",
    "fieldCode",
    "defaultSequence",
    "tabIds",
}

DEFINITION_KEYS = {"id", "key", "name", "fieldCode", "actNodeId", "actLineId"}


@dataclass(frozen=True)
class ReferenceFact:
    symbol: str
    key: str
    value: str
    path: str


class ValidationError(Exception):
    pass


def _read_json(path: Path) -> JSONValue:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, value: JSONValue) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, separators=(",", ":"))


def _join_pointer(base: str, key: str | int) -> str:
    token = str(key).replace("~", "~0").replace("/", "~1")
    if base == "":
        return f"/{token}"
    return f"{base}/{token}"


def _pointer_tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {pointer}")
    tokens = pointer[1:].split("/")
    return [token.replace("~1", "/").replace("~0", "~") for token in tokens]


def _get_at_pointer(doc: JSONValue, pointer: str) -> JSONValue:
    current = doc
    for token in _pointer_tokens(pointer):
        if isinstance(current, list):
            if token == "-":
                raise ValueError(f"Invalid '-' token for read pointer: {pointer}")
            idx = int(token)
            current = current[idx]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(f"Pointer does not exist: {pointer}")
    return current


def _resolve_parent(doc: JSONValue, pointer: str) -> tuple[JSONValue, str]:
    tokens = _pointer_tokens(pointer)
    if not tokens:
        raise ValueError("Root-level patch operation is not supported in this MVP")
    parent_tokens, last = tokens[:-1], tokens[-1]
    current = doc
    for token in parent_tokens:
        if isinstance(current, list):
            current = current[int(token)]
        else:
            current = current[token]
    return current, last


def _canonical_hash(value: JSONValue) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _value_preview(value: JSONValue, limit: int = 80) -> str:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _node_type(value: JSONValue) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _node_summary(path: str, value: JSONValue) -> str:
    t = _node_type(value)
    if isinstance(value, dict):
        keys = list(value.keys())[:6]
        return f"{path or '/'} ({t}, keys={keys}, size={len(value)})"
    if isinstance(value, list):
        return f"{path or '/'} ({t}, size={len(value)})"
    return f"{path or '/'} ({t}, value={_value_preview(value, 50)})"


def _normalize_symbol(key: str, value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        s = str(value).strip()
        if not s:
            return None
        return f"{key}:{s}"
    return None


def _scan_direct_references(obj: JSONValue, path: str) -> tuple[list[ReferenceFact], list[ReferenceFact]]:
    refs: list[ReferenceFact] = []
    defs: list[ReferenceFact] = []

    def walk(value: JSONValue, pointer: str) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                child_pointer = _join_pointer(pointer, k)
                if k in COMMON_REFERENCE_KEYS or k in PROC_REFERENCE_KEYS:
                    if k == "tabIds" and isinstance(v, list):
                        for idx, item in enumerate(v):
                            symbol = _normalize_symbol("tabId", item)
                            if symbol:
                                refs.append(ReferenceFact(symbol, "tabId", str(item), _join_pointer(child_pointer, idx)))
                    else:
                        symbol = _normalize_symbol(k, v)
                        if symbol:
                            refs.append(ReferenceFact(symbol, k, str(v), child_pointer))
                            if k in DEFINITION_KEYS:
                                defs.append(ReferenceFact(symbol, k, str(v), child_pointer))
                walk(v, child_pointer)
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                walk(item, _join_pointer(pointer, idx))

    walk(obj, path)
    return refs, defs


def _extract_process_xml_symbols(data: dict[str, Any]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    defs: dict[str, set[str]] = defaultdict(set)
    refs: dict[str, set[str]] = defaultdict(set)
    process_xml = str((data.get("processInfo") or {}).get("processXml") or "")
    if not process_xml:
        return defs, refs
    try:
        root = ET.fromstring(process_xml)
    except Exception:
        return defs, refs

    ns = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}

    for element in root.iter():
        element_id = element.get("id")
        if element_id:
            defs[f"actNodeId:{element_id}"].add(f"/processInfo/processXml#element/{element_id}")
            defs[f"id:{element_id}"].add(f"/processInfo/processXml#element/{element_id}")

        source_ref = element.get("sourceRef")
        if source_ref:
            refs[f"actNodeId:{source_ref}"].add(f"/processInfo/processXml#sourceRef/{source_ref}")
        target_ref = element.get("targetRef")
        if target_ref:
            refs[f"actNodeId:{target_ref}"].add(f"/processInfo/processXml#targetRef/{target_ref}")

    for flow in root.findall(".//bpmn:sequenceFlow", ns):
        flow_id = flow.get("id")
        if flow_id:
            defs[f"actLineId:{flow_id}"].add(f"/processInfo/processXml#sequenceFlow/{flow_id}")

    for tag in root.findall(".//bpmn:incoming", ns) + root.findall(".//bpmn:outgoing", ns):
        if tag.text and tag.text.strip():
            line_id = tag.text.strip()
            refs[f"actLineId:{line_id}"].add(f"/processInfo/processXml#{tag.tag}/{line_id}")

    return defs, refs


def _build_node_index(data: JSONValue) -> tuple[list[dict[str, Any]], dict[str, set[str]], dict[str, set[str]]]:
    index: list[dict[str, Any]] = []
    symbol_defs: dict[str, set[str]] = defaultdict(set)
    symbol_refs: dict[str, set[str]] = defaultdict(set)

    def walk(value: JSONValue, pointer: str) -> None:
        refs, defs = _scan_direct_references(value, pointer)
        for fact in defs:
            symbol_defs[fact.symbol].add(pointer or "/")
        for fact in refs:
            symbol_refs[fact.symbol].add(pointer or "/")

        index.append(
            {
                "path": pointer or "/",
                "type": _node_type(value),
                "summary": _node_summary(pointer, value),
                "hash": _canonical_hash(value),
                "defines": sorted({fact.symbol for fact in defs}),
                "references": sorted({fact.symbol for fact in refs}),
            }
        )

        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, _join_pointer(pointer, k))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                walk(item, _join_pointer(pointer, i))

    walk(data, "")

    if isinstance(data, dict):
        xml_defs, xml_refs = _extract_process_xml_symbols(data)
        for symbol, paths in xml_defs.items():
            symbol_defs[symbol].update(paths)
        for symbol, paths in xml_refs.items():
            symbol_refs[symbol].update(paths)

    return index, symbol_defs, symbol_refs


def build_proc_index(data: JSONValue) -> dict[str, Any]:
    node_index, symbol_defs, symbol_refs = _build_node_index(data)

    reverse_refs: dict[str, list[str]] = {}
    for symbol, def_paths in symbol_defs.items():
        refs = sorted(symbol_refs.get(symbol, set()))
        for def_path in def_paths:
            reverse_refs.setdefault(def_path, []).extend(refs)

    references = {
        symbol: {
            "definedAt": sorted(paths),
            "referencedBy": sorted(symbol_refs.get(symbol, set())),
        }
        for symbol, paths in symbol_defs.items()
    }

    return {
        "scope": "PROC_ONLY_MVP",
        "nodeCount": len(node_index),
        "nodes": node_index,
        "references": references,
        "reverseReferences": {k: sorted(set(v)) for k, v in reverse_refs.items()},
    }


def _node_map(data: JSONValue) -> dict[str, JSONValue]:
    result: dict[str, JSONValue] = {}

    def walk(value: JSONValue, pointer: str) -> None:
        result[pointer or "/"] = value
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, _join_pointer(pointer, k))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                walk(item, _join_pointer(pointer, i))

    walk(data, "")
    return result


def build_minimal_context(data: JSONValue, target_path: str, max_reverse: int = 20) -> dict[str, Any]:
    canonical_target = target_path if target_path != "" else "/"
    values_by_path = _node_map(data)
    if canonical_target not in values_by_path:
        raise ValueError(f"Target path does not exist: {target_path}")

    index_payload = build_proc_index(data)
    nodes = {node["path"]: node for node in index_payload["nodes"]}
    target_node = nodes[canonical_target]

    references = index_payload["references"]
    dependencies: list[dict[str, Any]] = []
    seen_dependency_paths: set[str] = set()

    for symbol in target_node.get("references", []):
        meta = references.get(symbol)
        if not meta:
            continue
        for path in meta.get("definedAt", []):
            if path in seen_dependency_paths:
                continue
            seen_dependency_paths.add(path)
            value = values_by_path.get(path)
            dependencies.append(
                {
                    "path": path,
                    "symbol": symbol,
                    "summary": nodes.get(path, {}).get("summary", f"{path} (virtual)"),
                    "content": value,
                }
            )

    reverse_summary: list[dict[str, Any]] = []
    target_definitions = target_node.get("defines", [])
    for symbol in target_definitions:
        meta = references.get(symbol)
        if not meta:
            continue
        for ref_path in meta.get("referencedBy", []):
            if ref_path == canonical_target:
                continue
            reverse_summary.append(
                {
                    "path": ref_path,
                    "symbol": symbol,
                    "summary": nodes.get(ref_path, {}).get("summary", f"{ref_path} (virtual)"),
                }
            )

    return {
        "scope": "PROC_ONLY_MVP",
        "target": {
            "path": canonical_target,
            "summary": target_node.get("summary"),
            "content": values_by_path[canonical_target],
            "defines": target_node.get("defines", []),
            "references": target_node.get("references", []),
        },
        "oneHopDependencies": dependencies,
        "oneHopReverseReferenceSummary": reverse_summary[:max_reverse],
        "editRule": "Return JSON Patch operations only; do not regenerate full PROC JSON.",
    }


def apply_json_patch(doc: JSONValue, operations: list[dict[str, Any]]) -> JSONValue:
    patched = copy.deepcopy(doc)
    for idx, op in enumerate(operations):
        action = op.get("op")
        path = op.get("path")
        if not isinstance(path, str):
            raise ValueError(f"Patch operation #{idx} has invalid path")

        parent, token = _resolve_parent(patched, path)

        if action == "replace":
            if isinstance(parent, list):
                parent[int(token)] = op["value"]
            else:
                if token not in parent:
                    raise KeyError(f"Replace path does not exist: {path}")
                parent[token] = op["value"]
        elif action == "add":
            if isinstance(parent, list):
                if token == "-":
                    parent.append(op["value"])
                else:
                    parent.insert(int(token), op["value"])
            else:
                parent[token] = op["value"]
        elif action == "remove":
            if isinstance(parent, list):
                del parent[int(token)]
            else:
                if token not in parent:
                    raise KeyError(f"Remove path does not exist: {path}")
                del parent[token]
        else:
            raise ValueError(f"Unsupported patch operation in MVP: {action}")

    return patched


def _flatten_field_references(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, val in value.items():
            if key in {"requireGroup", "disabledGroup", "hideGroup"} and isinstance(val, list):
                refs.extend(str(item) for item in val)
            else:
                refs.extend(_flatten_field_references(val))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_flatten_field_references(item))
    return refs


def validate_proc_json(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    process_info = data.get("processInfo") or {}
    process_xml = str(process_info.get("processXml") or "")

    xml_nodes_by_id: dict[str, ET.Element] = {}
    sequence_flows_by_id: dict[str, ET.Element] = {}

    if not process_xml:
        errors.append("Missing processInfo.processXml")
    else:
        try:
            root = ET.fromstring(process_xml)
        except Exception as exc:
            errors.append(f"processInfo.processXml cannot be parsed: {exc}")
            root = None

        if root is not None:
            for element in root.iter():
                element_id = element.get("id")
                if element_id:
                    if element_id in xml_nodes_by_id:
                        errors.append(f"Duplicate XML id: {element_id}")
                    xml_nodes_by_id[element_id] = element

            ns = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}
            for flow in root.findall(".//bpmn:sequenceFlow", ns):
                flow_id = flow.get("id")
                if flow_id:
                    if flow_id in sequence_flows_by_id:
                        errors.append(f"Duplicate sequenceFlow id: {flow_id}")
                    sequence_flows_by_id[flow_id] = flow

    node_conf = data.get("nodeConf") or []
    seen_node_ids: set[str] = set()
    for node in node_conf:
        node_id = str(node.get("actNodeId") or "")
        if not node_id:
            errors.append("nodeConf contains an entry without actNodeId")
            continue
        if node_id in seen_node_ids:
            errors.append(f"Duplicate nodeConf actNodeId: {node_id}")
        seen_node_ids.add(node_id)

        if xml_nodes_by_id and node_id not in xml_nodes_by_id:
            errors.append(f"nodeConf actNodeId does not exist in processXml: {node_id}")

        xml_element = xml_nodes_by_id.get(node_id)
        xml_name = str(xml_element.get("name", "")) if xml_element is not None else ""
        node_name = str(node.get("actNodeName") or "")
        if xml_name and node_name and node_name != xml_name:
            errors.append(f"Node name mismatch for {node_id}: nodeConf='{node_name}', XML='{xml_name}'")

        for apply in node.get("applyConf") or []:
            line_id = str(apply.get("actLineId") or "")
            if line_id and sequence_flows_by_id and line_id not in sequence_flows_by_id:
                errors.append(f"Gateway line does not exist in processXml: {line_id}")

        node_form_conf = node.get("nodeFormConf") or {}
        form_id = str((data.get("formDef") or {}).get("id") or "")
        mdl_form_id = str(node_form_conf.get("mdlFormId") or "")
        if form_id and mdl_form_id and form_id != mdl_form_id:
            errors.append(f"Form ID mismatch for node {node_id}")

    first_node_id = str(data.get("firstNodeId") or "")
    if first_node_id and xml_nodes_by_id and first_node_id not in xml_nodes_by_id:
        errors.append(f"firstNodeId does not exist in processXml: {first_node_id}")

    field_codes: set[str] = set()
    for field in (data.get("formDef") or {}).get("fieldList") or []:
        code = str(field.get("fieldCode") or "")
        if not code:
            continue
        if code in field_codes:
            errors.append(f"Duplicate formDef.fieldList fieldCode: {code}")
        field_codes.add(code)

    for node in node_conf:
        node_form_conf = node.get("nodeFormConf") or {}
        refs = _flatten_field_references((node_form_conf.get("actFormInfo") or {}))
        for ref in refs:
            ref_base = ref.split("|")[0]
            if ref and ref not in field_codes and ref_base not in field_codes:
                errors.append(f"Unknown form field '{ref}' in node '{node.get('actNodeId')}'")

    tab_ids: set[str] = set()
    for tab in data.get("tabConfig") or []:
        tab_id = str(tab.get("id") or "")
        if not tab_id:
            continue
        if tab_id in tab_ids:
            errors.append(f"Duplicate tabConfig id: {tab_id}")
        tab_ids.add(tab_id)

    for node in node_conf:
        groups = (node.get("nodeFormConf") or {}).get("actTabGroupInfo") or []
        if isinstance(groups, dict):
            groups = [groups]
        for group in groups:
            ids = group.get("tabIds") if isinstance(group, dict) else []
            for tab_id in ids or []:
                if tab_ids and str(tab_id) not in tab_ids:
                    errors.append(f"Unknown Tab ID '{tab_id}' for node '{node.get('actNodeId')}'")

    return errors


def apply_patch_and_validate(data: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    patched = apply_json_patch(data, operations)
    errors = validate_proc_json(patched)
    if errors:
        raise ValidationError("\n".join(errors))
    return patched


def _ensure_proc_file(path: Path) -> None:
    if not path.name.startswith("PROC_") or path.suffix.lower() != ".json":
        raise ValueError("This MVP only supports PROC_*.json files")


def _dump(data: Any, output: Path | None) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    if output is None:
        print(payload)
    else:
        output.write_text(payload + "\n", encoding="utf-8")


def _cli_index(args: argparse.Namespace) -> int:
    path = Path(args.input).resolve()
    _ensure_proc_file(path)
    data = _read_json(path)
    payload = build_proc_index(data)
    _dump(payload, Path(args.output).resolve() if args.output else None)
    return 0


def _cli_context(args: argparse.Namespace) -> int:
    path = Path(args.input).resolve()
    _ensure_proc_file(path)
    data = _read_json(path)
    payload = build_minimal_context(data, args.target, max_reverse=args.max_reverse)
    _dump(payload, Path(args.output).resolve() if args.output else None)
    return 0


def _cli_apply_patch(args: argparse.Namespace) -> int:
    path = Path(args.input).resolve()
    _ensure_proc_file(path)
    data = _read_json(path)
    patch_operations = _read_json(Path(args.patch).resolve())
    if not isinstance(patch_operations, list):
        raise ValueError("Patch file must be a JSON array of RFC6902-like operations")

    if args.skip_validation:
        updated = apply_json_patch(data, patch_operations)
    else:
        updated = apply_patch_and_validate(data, patch_operations)

    out_path = path if args.in_place else Path(args.output).resolve() if args.output else None
    if out_path is None:
        _dump(updated, None)
    else:
        _write_json(out_path, updated)
    return 0


def _cli_validate(args: argparse.Namespace) -> int:
    path = Path(args.input).resolve()
    _ensure_proc_file(path)
    data = _read_json(path)
    errors = validate_proc_json(data)
    if errors:
        print("PROC validation failed:")
        for e in errors:
            print(f"- {e}")
        return 1
    print(f"PROC validation passed: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PROC JSON local edit MVP: index + minimal context + patch apply + validation"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Build recursive node index and reference map")
    p_index.add_argument("--input", required=True, help="Path to PROC_*.json")
    p_index.add_argument("--output", help="Optional output JSON file")
    p_index.set_defaults(func=_cli_index)

    p_context = sub.add_parser("context", help="Build minimal one-hop edit context for a target path")
    p_context.add_argument("--input", required=True, help="Path to PROC_*.json")
    p_context.add_argument("--target", required=True, help="JSON Pointer target path, e.g. /nodeConf/0")
    p_context.add_argument("--max-reverse", type=int, default=20)
    p_context.add_argument("--output", help="Optional output JSON file")
    p_context.set_defaults(func=_cli_context)

    p_patch = sub.add_parser("apply-patch", help="Apply JSON Patch operations and validate")
    p_patch.add_argument("--input", required=True, help="Path to PROC_*.json")
    p_patch.add_argument("--patch", required=True, help="Patch JSON file (array of operations)")
    p_patch.add_argument("--output", help="Output path when not using --in-place")
    p_patch.add_argument("--in-place", action="store_true", help="Overwrite input file")
    p_patch.add_argument("--skip-validation", action="store_true", help="Apply patch without validation")
    p_patch.set_defaults(func=_cli_apply_patch)

    p_validate = sub.add_parser("validate", help="Run PROC-only validation checks")
    p_validate.add_argument("--input", required=True, help="Path to PROC_*.json")
    p_validate.set_defaults(func=_cli_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValidationError as exc:
        print("PROC patch validation failed:")
        for line in str(exc).splitlines():
            print(f"- {line}")
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
