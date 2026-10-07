import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.compare_positioning import main


class ComparisonCLITest(unittest.TestCase):
    def run_main(self, *args):
        with patch.object(sys, 'argv', ['compare_positioning', *map(str, args)]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            main()

    def test_demo_report_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'report.json'
            self.run_main('--demo', '--output', output)
            original = output.read_bytes()
            report = json.loads(original)
            self.assertEqual(report['provenance']['kind'], 'synthetic')
            self.assertEqual(report['split']['seed'], 2026)
            with self.assertRaises(SystemExit):
                self.run_main('--demo', '--output', output)
            self.assertEqual(original, output.read_bytes())

    def test_real_training_requires_manifest_and_operator_review(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'report.json'
            with self.assertRaises(SystemExit):
                self.run_main('--training', '/nonexistent/training.csv', '--output', output)
            self.assertFalse(output.exists())

    def test_direct_cli_works_from_another_directory(self):
        script = Path(__file__).resolve().parents[1]/'tools/compare_positioning.py'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'report.json'
            result = subprocess.run([sys.executable, str(script), '--demo', '--mode', 'spatial', '--output', str(output)], cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_bytes())['split']['mode'], 'spatial')


if __name__ == '__main__':
    unittest.main()
