import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "proc_json_local_edit.py"
spec = importlib.util.spec_from_file_location("proc_json_local_edit", SCRIPT_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def _sample_proc() -> dict:
    return {
        "processInfo": {
            "id": "proc-1",
            "processName": "Demo Proc",
            "processXml": "<?xml version=\"1.0\" encoding=\"UTF-8\"?><bpmn:definitions xmlns:bpmn=\"http://www.omg.org/spec/BPMN/20100524/MODEL\"><bpmn:process id=\"Process_1\" isExecutable=\"true\"><bpmn:startEvent id=\"StartEvent_1\"><bpmn:outgoing>Flow_1</bpmn:outgoing></bpmn:startEvent><bpmn:userTask id=\"UserTask_1\" name=\"New\"><bpmn:incoming>Flow_1</bpmn:incoming><bpmn:outgoing>Flow_2</bpmn:outgoing></bpmn:userTask><bpmn:endEvent id=\"EndEvent_1\"><bpmn:incoming>Flow_2</bpmn:incoming></bpmn:endEvent><bpmn:sequenceFlow id=\"Flow_1\" sourceRef=\"StartEvent_1\" targetRef=\"UserTask_1\"/><bpmn:sequenceFlow id=\"Flow_2\" sourceRef=\"UserTask_1\" targetRef=\"EndEvent_1\"/></bpmn:process></bpmn:definitions>",
            "mdlFormId": "form-1",
        },
        "firstNodeId": "UserTask_1",
        "tabConfig": [{"id": "tab-1", "tabName": "Main"}],
        "formDef": {
            "id": "form-1",
            "fieldList": [{"fieldCode": "title"}, {"fieldCode": "desc"}],
            "formInfo": {},
        },
        "nodeConf": [
            {
                "actNodeId": "UserTask_1",
                "actNodeName": "New",
                "nodeFormConf": {
                    "mdlFormId": "form-1",
                    "actFormInfo": {"basicInfo": {"requireGroup": ["title"]}},
                    "actTabGroupInfo": [{"tabIds": ["tab-1"]}],
                },
                "applyConf": [{"actLineId": "Flow_2"}],
            }
        ],
    }


class ProcJsonLocalEditTests(unittest.TestCase):
    def test_build_index_and_context(self):
        proc = _sample_proc()
        index = module.build_proc_index(proc)
        self.assertEqual(index["scope"], "PROC_ONLY_MVP")
        self.assertGreater(index["nodeCount"], 10)
        self.assertIn("actNodeId:UserTask_1", index["references"])

        context = module.build_minimal_context(proc, "/nodeConf/0")
        self.assertEqual(context["target"]["path"], "/nodeConf/0")
        dependency_paths = {item["path"] for item in context["oneHopDependencies"]}
        self.assertIn("/processInfo/processXml#element/UserTask_1", dependency_paths)

    def test_apply_patch_and_validate(self):
        proc = _sample_proc()
        patch = [
            {"op": "replace", "path": "/processInfo/processName", "value": "Demo Proc v2"},
            {"op": "replace", "path": "/nodeConf/0/actNodeName", "value": "New"},
        ]
        updated = module.apply_patch_and_validate(proc, patch)
        self.assertEqual(updated["processInfo"]["processName"], "Demo Proc v2")

    def test_detect_dangling_reference_after_patch(self):
        proc = _sample_proc()
        patch = [{"op": "replace", "path": "/firstNodeId", "value": "UserTask_MISSING"}]
        with self.assertRaises(module.ValidationError):
            module.apply_patch_and_validate(proc, patch)

    def test_cli_apply_patch_to_file(self):
        proc = _sample_proc()
        patch = [{"op": "replace", "path": "/processInfo/processName", "value": "Renamed"}]
        with tempfile.TemporaryDirectory() as td:
            proc_path = Path(td) / "PROC_sample.json"
            patch_path = Path(td) / "patch.json"
            out_path = Path(td) / "out.json"
            proc_path.write_text(json.dumps(proc), encoding="utf-8")
            patch_path.write_text(json.dumps(patch), encoding="utf-8")

            exit_code = module.main(
                [
                    "apply-patch",
                    "--input",
                    str(proc_path),
                    "--patch",
                    str(patch_path),
                    "--output",
                    str(out_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            output = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(output["processInfo"]["processName"], "Renamed")


if __name__ == "__main__":
    unittest.main()
