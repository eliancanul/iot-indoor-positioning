import sys
import types
import unittest
from unittest.mock import patch

fake_mqtt = types.ModuleType('paho.mqtt.client')
fake_mqtt.Client = object
fake_mqtt.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
sys.modules['paho'] = types.ModuleType('paho')
sys.modules['paho.mqtt'] = types.ModuleType('paho.mqtt')
sys.modules['paho.mqtt.client'] = fake_mqtt

from mqtt_manager import MQTTManager


class ActivationGuardTest(unittest.TestCase):
    def test_activation_rejects_invalid_geometry_before_subscribing(self):
        nodes = [
            {'node_id': 'a', 'topic': 'a', 'pos_x': 0.0, 'pos_y': 0.0},
            {'node_id': 'b', 'topic': 'b', 'pos_x': 2.0, 'pos_y': 1.0},
            {'node_id': 'c', 'topic': 'c', 'pos_x': 4.0, 'pos_y': 2.0},
        ]
        manager = MQTTManager()
        with patch.object(manager, '_ensure_client'), patch('mqtt_manager.db.listar_esp32_por_area', return_value=nodes):
            ok, reason = manager.activar_area(77)
        self.assertFalse(ok)
        self.assertIn('L', reason)
        self.assertNotIn(77, manager.active_areas)


if __name__ == '__main__':
    unittest.main()
