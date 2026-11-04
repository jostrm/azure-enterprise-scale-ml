import unittest

from tests.support import FACTORY_TEMPLATE

from ml_agent.configuration import read_json
from ml_agent.usecases import AIR, CHURN, CHURN_LEAF, churn_scenario, expected_names, model_name, usecase


class UseCaseTests(unittest.TestCase):
    def test_churn_copy_reuses_the_template_contract_with_synthetic_lake_data(self):
        template = read_json(FACTORY_TEMPLATE / "user-config" / "model" / "scenarios" / "churn.json")
        scenario = churn_scenario(template)
        for key in ("features", "target", "categorical_features", "split", "custom", "quality"):
            self.assertEqual(scenario[key], template[key])
        dataset = scenario["dataset"]
        self.assertEqual((dataset["provider"], dataset["status"]), ("lake", "configured"))
        self.assertEqual(dataset["synthetic"], {"generator": "telco-churn", "seed": 49, "rows": 7043})
        self.assertNotIn("slug", dataset)
        self.assertNotIn("kaggle", str(dataset).lower())
        self.assertEqual(scenario["example_leaves"], [CHURN_LEAF])
        from ml_model_factory.config import validate_scenario

        validate_scenario(scenario)
        with self.assertRaises(ValueError):
            churn_scenario({**template, "name": "diabetes"})

    def test_m49_and_m05_names_follow_the_esml_model_prefix_contract(self):
        self.assertEqual(model_name(CHURN), "M49_49_agent_training_ml_churn_prediction")
        self.assertEqual(model_name(AIR), "M05_air_passengers")
        names = expected_names(CHURN)
        self.assertTrue(all(value.startswith("M49_") for value in names.values()))
        self.assertEqual(names["training_experiment"], f"M49_{CHURN}_IN_2_GOLD_TRAINING_MANUAL")
        self.assertEqual(usecase(CHURN)["model_number"], 49)
        with self.assertRaises(ValueError):
            usecase("titanic")


if __name__ == "__main__":
    unittest.main()
