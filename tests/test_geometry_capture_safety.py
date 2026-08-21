import math
import sys
import types
import unittest

mqtt = types.ModuleType('paho.mqtt.client')
mqtt.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
mqtt.Client = object
sys.modules.setdefault('paho', types.ModuleType('paho'))
sys.modules.setdefault('paho.mqtt', types.ModuleType('paho.mqtt'))
sys.modules['paho.mqtt.client'] = mqtt

from mqtt_manager import validar_geometria_l, triangulos, circulos


NODES = [
    {'node_id': 'ESP32_0', 'pos_x': 0.0, 'pos_y': 0.0},
    {'node_id': 'ESP32_1', 'pos_x': 5.0, 'pos_y': 0.0},
    {'node_id': 'ESP32_2', 'pos_x': 0.0, 'pos_y': 2.0},
]


class GeometryAndCaptureSafetyTest(unittest.TestCase):
    def test_valid_l_geometry_is_accepted(self):
        self.assertEqual(validar_geometria_l(NODES), (True, None))

    def test_collinear_or_misaligned_nodes_are_rejected(self):
        bad = [
            {'node_id': 'a', 'pos_x': 0.0, 'pos_y': 0.0},
            {'node_id': 'b', 'pos_x': 2.0, 'pos_y': 1.0},
            {'node_id': 'c', 'pos_x': 4.0, 'pos_y': 2.0},
        ]
        ok, reason = validar_geometria_l(bad)
        self.assertFalse(ok)
        self.assertIn('L', reason)

    def test_circles_uses_area_bounds_not_node_rectangle(self):
        point = (6.0, 4.0)
        distances = [math.hypot(point[0] - n['pos_x'], point[1] - n['pos_y']) for n in NODES]
        x, y = circulos(distances, NODES, area_bounds=(8.0, 6.0))
        self.assertAlmostEqual(x, point[0], places=2)
        self.assertAlmostEqual(y, point[1], places=2)

    def test_impossible_distances_return_no_triangle_estimate(self):
        self.assertIsNone(triangulos([1.0, 1.0, 10.0], NODES, area_bounds=(8.0, 6.0)))


if __name__ == '__main__':
    unittest.main()
