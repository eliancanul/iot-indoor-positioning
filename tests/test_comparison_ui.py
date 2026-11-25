"""Streamlit state/interaction tests. No radio hardware or network connection."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import database as db


class ComparisonUITest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patch = patch.object(db, 'DB_PATH', str(Path(self.directory.name)/'ui-synthetic.db'))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.directory.cleanup()

    def app(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'), default_timeout=20)
        app.session_state['autenticado'] = True
        app.run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_starts_offline_without_activating_mqtt(self):
        with patch('mqtt_manager.MQTTManager.sincronizar_areas') as sync:
            app = self.app()
            self.assertEqual(app.sidebar.radio[0].value, '📍 Comparar')
            self.assertTrue(any('Datos simulados' in warning.value for warning in app.warning))
            sync.assert_not_called()

    def test_compare_repeat_parameter_change_and_spatial_flow(self):
        app = self.app()
        app.button(key='lab_compare').click().run()
        self.assertEqual(len(app.exception), 0)
        first = app.session_state['lab_result']
        self.assertEqual(first['metrics']['tree']['n'], 45)
        app.button(key='lab_compare').click().run()
        self.assertEqual(first, app.session_state['lab_result'])
        app.slider(key='lab_k').set_value(3).run()
        self.assertNotIn('lab_result', app.session_state)
        app.radio(key='lab_evaluation').set_value('Una posición no aprendida').run()
        app.button(key='lab_compare').click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state['lab_result']['split']['mode'], 'spatial')
        self.assertEqual(app.session_state['lab_result']['metrics']['tree']['n'], 3)
        app.button(key='lab_predict').click().run()
        self.assertTrue(any('Posición estimada:' in m.value for m in app.markdown))
        self.assertEqual(len(app.exception), 0)

    def test_switching_source_clears_stale_results_and_shows_empty_state(self):
        app = self.app()
        app.button(key='lab_compare').click().run()
        app.radio(key='lab_source').set_value('Export de captura').run()
        self.assertNotIn('lab_result', app.session_state)
        self.assertTrue(any('Carga CSV y manifiesto' in message.value for message in app.info))
        self.assertEqual(len(app.exception), 0)
        app.radio(key='lab_source').set_value('Demo sintética').run()
        self.assertNotIn('lab_result', app.session_state)
        self.assertEqual(len(app.exception), 0)

    def test_configuration_without_area_explains_next_step(self):
        app = self.app()
        with patch('database.listar_areas', return_value=[]):
            app.sidebar.radio[0].set_value('🔧 Configuración').run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('Crea un área' in item.value for item in app.info))


if __name__ == '__main__':
    unittest.main()
