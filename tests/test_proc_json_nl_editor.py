from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".github/skills/process-json-editor/scripts/proc-json-nl-editor.py"
VALIDATE_SCRIPT = REPO_ROOT / ".github/skills/process-json-editor/scripts/validate-process-json.sh"
MD5_SCRIPT = REPO_ROOT / ".github/skills/process-json-editor/scripts/md5.sh"
FIXTURE_DIR = REPO_ROOT / "tests/fixtures/process_main_fixture"
FIXTURE_FILE = FIXTURE_DIR / "PROC_fixture.json"


class ProcJsonNlEditorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="proc-json-editor-tests-"))
        shutil.copytree(FIXTURE_DIR, self.temp_dir / FIXTURE_DIR.name)
        self.fixture_dir = self.temp_dir / FIXTURE_DIR.name
        self.proc_path = self.fixture_dir / FIXTURE_FILE.name

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def run_cli(self, *args: str, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["python3", str(SCRIPT), *args],
            capture_output=True,
            text=True,
        )
        if expect_success and completed.returncode != 0:
            self.fail(f"command failed: {completed.stderr or completed.stdout}")
        if not expect_success and completed.returncode == 0:
            self.fail(f"command unexpectedly succeeded: {completed.stdout}")
        return completed

    def load_json(self) -> dict:
        with self.proc_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_find_returns_node_candidate_from_natural_language(self) -> None:
        completed = self.run_cli(
            "find",
            "--target",
            str(self.fixture_dir),
            "--query",
            "Approval 节点",
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["candidates"])
        self.assertEqual(payload["candidates"][0]["pointer"], "/nodeConf/1")

    def test_edit_rename_node_updates_json_and_process_xml(self) -> None:
        self.run_cli(
            "edit",
            "--target",
            str(self.proc_path),
            "--request",
            '将节点 "Approval" 的名称改为 "Review"',
        )
        data = self.load_json()
        self.assertEqual(data["nodeConf"][1]["actNodeName"], "Review")
        self.assertIn('id="UserTask_Approval" name="Review"', data["processInfo"]["processXml"])
        validation = subprocess.run(
            ["bash", str(VALIDATE_SCRIPT), "-p", str(self.proc_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)

    def test_edit_field_default_value_syncs_fieldlist_and_forminfo(self) -> None:
        self.run_cli(
            "edit",
            "--target",
            str(self.proc_path),
            "--request",
            '将字段 "ShortDescription" 的默认值改为 "N/A"',
        )
        data = self.load_json()
        self.assertEqual(data["formDef"]["fieldList"][0]["defaultValue"], "N/A")
        field_node = data["formDef"]["formInfo"]["properties"]["basicInfo"]["properties"]["ShortDescription"]
        self.assertEqual(field_node["default"], "N/A")
        self.assertEqual(field_node["x-props"]["defaultValue"], "N/A")

    def test_apply_rejects_direct_edit_of_protected_reference_path(self) -> None:
        ops_file = self.temp_dir / "ops.json"
        ops_file.write_text(
            json.dumps(
                [
                    {
                        "op": "replace",
                        "path": "/nodeConf/1/actNodeId",
                        "value": "UserTask_Review",
                    }
                ]
            ),
            encoding="utf-8",
        )
        completed = self.run_cli(
            "apply",
            "--target",
            str(self.proc_path),
            "--ops-file",
            str(ops_file),
            expect_success=False,
        )
        self.assertIn("Protected path", completed.stderr)

    def test_md5_script_supports_linux_and_proc_first_ordering(self) -> None:
        adv_path = self.fixture_dir / "ADV_example_1_00000000-0000-0000-0000-000000000000.json"
        adv_path.write_text("{}", encoding="utf-8")
        completed = subprocess.run(
            ["bash", str(MD5_SCRIPT), "-d", str(self.fixture_dir), "-e", "env-1", "-v", "1.0.0"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

        readme_lines = (self.fixture_dir / "README.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(readme_lines[0], "PROC_fixture.json")
        self.assertEqual(readme_lines[1], adv_path.name)

        consistency_lines = (self.fixture_dir / "CONSISTENCY.MD5").read_text(encoding="utf-8").splitlines()
        self.assertEqual(consistency_lines[0], "env:env-1")
        self.assertEqual(consistency_lines[1], "version:1.0.0")
        self.assertTrue(consistency_lines[2].startswith("PROC_fixture.json:"))


if __name__ == "__main__":
    unittest.main()
