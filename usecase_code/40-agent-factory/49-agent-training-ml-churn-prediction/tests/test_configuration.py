from copy import deepcopy
import tempfile
import unittest
from pathlib import Path

from tests.support import TEMPLATE, consumer

from ml_agent.configuration import fingerprint, paths, validate
from ml_agent.usecases import AIR, CHURN


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.config = consumer(Path(self.temporary.name), instantiate=False)

    def tearDown(self):
        self.temporary.cleanup()

    def test_init_config_binds_the_reviewed_scope_and_common_lake(self):
        config = self.config
        self.assertEqual(config["owner"], "aif49-project001-dev")
        self.assertEqual(config["shared_lake"], {"account_url": "https://lakeaccount.blob.core.windows.net",
                                                 "container": "lake3", "datastore": "esml_shared_lake",
                                                 "prefix": "mlops/v1"})
        self.assertEqual(config["usecases"][AIR]["compute"], "m05-cpu-dev")
        self.assertEqual(config["usecases"][CHURN]["compute"], "m02-cpu-dev")
        location = paths(config)
        self.assertTrue(str(location.esml(CHURN)).endswith(
            r"ml-environment\outputs\49-agent-training-ml-churn-prediction\custom-pipeline\esml"))
        self.assertEqual(location.state.name, "v1")

    def test_invalid_or_template_internal_configuration_is_rejected(self):
        cases = {
            "owner": lambda value: value.update(owner="aif49-project002-dev"),
            "state": lambda value: value.update(state_root=str(TEMPLATE / ".agent-factory")),
            "endpoint": lambda value: value.update(project_endpoint="http://example.com"),
            "usecases": lambda value: value["usecases"].pop(AIR),
            "champion": lambda value: value["usecases"][AIR].update(champion_model_id="azureml:other:2"),
        }
        for name, change in cases.items():
            with self.subTest(name):
                value = deepcopy(self.config)
                change(value)
                with self.assertRaises(ValueError):
                    validate(value)

    def test_fingerprint_changes_with_any_setting(self):
        changed = deepcopy(self.config)
        changed["usecases"][CHURN]["inference_rows"] = 10
        self.assertNotEqual(fingerprint(self.config), fingerprint(changed))


if __name__ == "__main__":
    unittest.main()
