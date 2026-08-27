from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class MessagingCapabilityParityTests(unittest.TestCase):
    def test_transplanted_capability_manifest_matches_pinned_baseline(self):
        baseline = json.loads(
            (Path(__file__).parent / "fixtures" / "capability-parity.json").read_text(
                encoding="utf-8"
            )
        )
        source_root = SERVICE_ROOT / "marvi_messaging" / "engine"
        if not source_root.is_dir():
            self.skipTest("transplant has not created the Marvi engine yet")

        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            output = temporary_root / "capabilities.json"
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            subprocess.run(
                [
                    sys.executable,
                    str(SERVICE_ROOT / "tools" / "capture_parity.py"),
                    str(source_root),
                    "--home",
                    str(temporary_root / "profile"),
                    "--output",
                    str(output),
                ],
                check=True,
                env=environment,
                timeout=120,
            )
            actual = json.loads(output.read_text(encoding="utf-8"))
        for name, expected in baseline["sections"].items():
            section = actual[name]
            self.assertEqual(len(section), expected["count"], name)
            self.assertEqual(_digest(section), expected["sha256"], name)


if __name__ == "__main__":
    unittest.main()
