"""Regression for a failed repeated comparison, isolated from MQTT and user data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROBE = r'''
from pathlib import Path
import os
import socket
import sqlite3
import sys
import types
from unittest.mock import patch
from urllib.parse import unquote, urlparse

root, work = map(Path, sys.argv[1:3])
safe = work / "database"
safe.mkdir()
os.environ["MPLBACKEND"] = "Agg"
os.environ["MPLCONFIGDIR"] = str(work / "fonts")
os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
sys.dont_write_bytecode = True

def guard(event, args):
    if event == "sqlite3.connect":
        value = os.fspath(args[0])
        path = Path(unquote(urlparse(value).path) if value.startswith("file:") else value).resolve()
        if not path.is_relative_to(safe):
            raise PermissionError("Test database must be temporary")
    if event in {"socket.connect", "socket.bind", "socket.getaddrinfo", "subprocess.Popen", "os.system"}:
        raise PermissionError("This comparison test is offline")
    if event == "socket.__new__" and args[1] in (socket.AF_INET, socket.AF_INET6):
        raise PermissionError("IP sockets are disabled")

sys.addaudithook(guard)
for action in (
    lambda: socket.socket(socket.AF_INET),
    lambda: socket.getaddrinfo("synthetic.invalid", 1883),
    lambda: sqlite3.connect(str(work / "forbidden.db")),
):
    try:
        action()
        raise AssertionError("Isolation guard did not block")
    except PermissionError:
        pass
assert not (work / "forbidden.db").exists()

def forbidden_client(*args, **kwargs):
    raise AssertionError("No MQTT client is allowed")

class OfflineManager:
    def get_estado(self):
        return {"connected": False, "active_area": None, "active_areas": [],
                "active_topics": [], "total_topics": 0, "nodos": [], "areas": {}}
    def sincronizar_areas(self, *args, **kwargs):
        raise AssertionError("Comparison must not activate MQTT")

paho, package, client = [types.ModuleType(n) for n in ("paho", "paho.mqtt", "paho.mqtt.client")]
paho.__path__ = package.__path__ = []
paho.mqtt, package.client = package, client
client.Client = forbidden_client
client.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
sys.modules.update({"paho": paho, "paho.mqtt": package, "paho.mqtt.client": client})
sys.path.insert(0, str(root))
import database as db
db.DB_PATH = str(safe / "comparison.db")
import mqtt_manager
manager = OfflineManager()
mqtt_manager.MQTTManager = OfflineManager
mqtt_manager.get_manager = lambda: manager
mqtt_manager._manager_instance = manager
import calibration
assert calibration.mqtt.Client is forbidden_client
assert mqtt_manager.mqtt.Client is forbidden_client
assert "app" not in sys.modules and not Path(db.DB_PATH).exists()

from streamlit.testing.v1 import AppTest
import comparison_panel as panel
app = AppTest.from_file(str(root / "app.py"), default_timeout=30)
app.session_state["autenticado"] = True
app.run()
assert not app.exception
app.button(key="lab_compare").click().run()
assert not app.exception
previous = app.session_state["lab_result"]
assert previous["samples"] and app.dataframe and app.get("download_button")
with patch.object(panel, "compare", side_effect=panel.DatasetError("Synthetic comparison failure")):
    app.button(key="lab_compare").click().run()
assert not app.exception
assert [e.value for e in app.error] == ["Synthetic comparison failure"]
assert "lab_result" not in app.session_state
assert not any(m.label == "Error medio" for m in app.metric)
assert not app.dataframe and not app.get("download_button")
app.button(key="lab_compare").click().run()
assert not app.exception and not app.error
assert app.session_state["lab_result"] == previous
'''


class ComparisonFailureUITest(unittest.TestCase):
    def test_failed_repeat_clears_previous_result_and_allows_retry(self):
        root = Path(__file__).resolve().parents[1]
        env = {k: v for k, v in os.environ.items()
               if k in {"PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL"}}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryDirectory(prefix="comparison-regression-") as work:
            result = subprocess.run(
                [sys.executable, "-c", PROBE, str(root), work],
                cwd=work, env=env, capture_output=True, text=True, timeout=90,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
