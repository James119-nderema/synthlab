import pandas as pd
from django.test import SimpleTestCase

from lab.services.cleaner import clean, profile
from lab.views import _build_steps
from lab.services.dp_accounting import BudgetLedgerCapError, estimate_delta, suggest_noise_multiplier
from lab.services.generator import evaluate_fidelity, generate_synthetic_dataset
from lab.services.privacy import run_privacy_check
from lab.services.privacy_definition import build_student_table, group_split_by_student
from lab.services.simulator import simulate


class WorkflowPipelineTests(SimpleTestCase):
    def test_academic_dp_pipeline_order_matches_expected_steps(self):
        steps = _build_steps("prepare")
        labels = [step["label"] for step in steps]

        required_sequence = [
            "Real Academic Data",
            "Data Preprocessing",
            "Define Student-Level Privacy",
            "Configure Privacy Mechanism",
            "Train Synthetic Data Generator with Differential Privacy",
            "Generate Synthetic Records",
            "Validate Synthetic Data",
            "Privacy Evaluation",
            "Utility Evaluation",
            "Privacy–Utility Analysis",
            "Train AI Analytics Model",
            "Evaluate Predictions",
            "Privacy-Preserving Academic Insights",
        ]

        for expected_label in required_sequence:
            self.assertIn(expected_label, labels)

        for current, next_label in zip(required_sequence, required_sequence[1:]):
            self.assertLess(labels.index(current), labels.index(next_label))

    def test_academic_dp_pipeline_has_unique_route_targets(self):
        steps = _build_steps("prepare")
        urls = [step["url"] for step in steps]

        self.assertEqual(len(urls), len(set(urls)))

    def test_each_pipeline_step_has_distinct_template(self):
        from lab import views

        distinct_templates = {
            views.real_data_page.__name__: "lab/real_data.html",
            views.data_preprocessing_page.__name__: "lab/data_preprocessing.html",
            views.student_privacy_page.__name__: "lab/student_privacy.html",
            views.privacy_mechanism_page.__name__: "lab/privacy_mechanism.html",
            views.dp_generator_page.__name__: "lab/dp_generator.html",
            views.synthetic_records_page.__name__: "lab/synthetic_records.html",
            views.synthetic_validation_page.__name__: "lab/synthetic_validation.html",
            views.privacy_evaluation_page.__name__: "lab/privacy_evaluation.html",
            views.utility_evaluation_page.__name__: "lab/utility_evaluation.html",
            views.privacy_utility_analysis_page.__name__: "lab/privacy_utility_analysis.html",
            views.ai_analytics_model_page.__name__: "lab/ai_analytics_model.html",
            views.evaluate_predictions_page.__name__: "lab/evaluate_predictions.html",
            views.academic_insights_page.__name__: "lab/academic_insights.html",
        }

        self.assertEqual(len(distinct_templates), len(set(distinct_templates.values())))


class SimulatorServiceTests(SimpleTestCase):
    def test_simulate_returns_dataframe_with_expected_shape(self):
        schema = [
            {"name": "customer_id", "type": "uuid"},
            {"name": "age", "type": "integer", "params": {"min": 18, "max": 80}},
            {"name": "country", "type": "country"},
            {"name": "has_discount", "type": "boolean", "params": {"probability": 0.25}},
        ]

        dataframe = simulate(schema, 25, seed=7)

        self.assertEqual(len(dataframe), 25)
        self.assertEqual(list(dataframe.columns), ["customer_id", "age", "country", "has_discount"])
        self.assertTrue(dataframe["age"].between(18, 80).all())
        self.assertTrue(dataframe["has_discount"].isin([True, False]).all())

    def test_simulate_inserts_missing_values_when_requested(self):
        schema = [{"name": "income", "type": "float", "params": {"distribution": "normal", "mean": 50000, "std": 1000}, "missing_pct": 0.2}]

        dataframe = simulate(schema, 100, seed=11)

        self.assertGreater(dataframe["income"].isna().sum(), 0)
        self.assertEqual(dataframe.shape, (100, 1))

    def test_simulate_rejects_invalid_schema(self):
        with self.assertRaises(ValueError):
            simulate([], 10)


class CleanerServiceTests(SimpleTestCase):
    def test_profile_marks_identifier_columns(self):
        dataframe = pd.DataFrame({
            "student_id": ["S-1001", "S-1002", "S-1003"],
            "score": [87, 92, 78],
            "school": ["North", "South", "West"],
        })

        result = profile(dataframe)

        self.assertTrue(result["columns"]["student_id"]["is_identifier"])
        self.assertFalse(result["columns"]["school"]["is_identifier"])

    def test_clean_removes_duplicates_and_fills_missing_values(self):
        dataframe = pd.DataFrame({
            "student_id": ["A1", "A1", "A2", "A3"],
            "score": [90, 90, 85, None],
            "grade": ["A", "A", "B", None],
            "school": ["North", "North", "South", "North"],
        })

        cleaned, report = clean(dataframe, {
            "drop_duplicate_rows": True,
            "drop_identifier_columns": True,
            "missing_numeric_policy": "mean",
            "missing_categorical_policy": "mode",
            "outlier_strategy": "none",
        })

        self.assertEqual(len(cleaned), 3)
        self.assertNotIn("student_id", cleaned.columns)
        self.assertTrue(cleaned["score"].notna().all())
        self.assertTrue(cleaned["grade"].notna().all())
        self.assertIn("rows_removed", report)


class GeneratorServiceTests(SimpleTestCase):
    def test_generate_synthetic_dataset_returns_matching_shape(self):
        dataframe = pd.DataFrame({
            "student_id": [f"S-{i}" for i in range(1, 31)],
            "school": ["North", "South", "East"] * 10,
            "score": [80 + (i % 20) for i in range(30)],
            "passed": [bool(i % 2) for i in range(30)],
        })

        synthetic = generate_synthetic_dataset(dataframe, n_rows=50, seed=7)

        self.assertEqual(len(synthetic), 50)
        self.assertEqual(list(synthetic.columns), list(dataframe.columns))
        self.assertTrue({"student_id", "school", "score", "passed"}.issubset(set(synthetic.columns)))

    def test_evaluate_fidelity_returns_scores(self):
        real_df = pd.DataFrame({
            "school": ["North", "South", "North", "East", "South"],
            "score": [74, 88, 90, 71, 82],
            "passed": [True, True, True, False, True],
        })
        synthetic_df = pd.DataFrame({
            "school": ["North", "South", "East", "North", "South"],
            "score": [77, 83, 78, 84, 80],
            "passed": [True, False, True, True, True],
        })

        result = evaluate_fidelity(real_df, synthetic_df)

        self.assertIn("score", result)
        self.assertIn("details", result)
        self.assertTrue(0 <= result["score"] <= 1)


class PrivacyServiceTests(SimpleTestCase):
    def test_run_privacy_check_returns_risk_summary(self):
        real = pd.DataFrame({
            "age": [20, 21, 22, 23, 24, 25],
            "school": ["A", "A", "B", "B", "C", "C"],
            "score": [80, 82, 85, 87, 91, 93],
        })
        synthetic = pd.DataFrame({
            "age": [20, 21, 22, 23, 24, 25],
            "school": ["A", "A", "B", "B", "C", "C"],
            "score": [81, 83, 84, 86, 90, 92],
        })

        result = run_privacy_check(real, synthetic)

        self.assertIn("risk_level", result)
        self.assertIn("verdict", result)
        self.assertIn("dcr", result)
        self.assertIn("membership_inference", result)
        self.assertIn("exact_match_pct", result)
        self.assertIn("recommendations", result)
        self.assertTrue(0 <= result["exact_match_pct"] <= 100)


class StudentLevelDPLifecycleTests(SimpleTestCase):
    def test_contribution_bounding_keeps_groups_intact(self):
        df = pd.DataFrame({
            "student_id": ["s1", "s1", "s1", "s2", "s2", "s3"],
            "department": ["CS", "CS", "CS", "Math", "Math", "CS"],
            "final_grade": [90, 88, 84, 70, 72, 75],
            "gpa": [3.8, 3.9, 3.7, 3.2, 3.4, 3.1],
        })

        bounded = build_student_table(df, {"student_id_col": "student_id", "max_rows_per_student": 2})
        self.assertTrue(bounded["student_id"].nunique() == 3)
        self.assertTrue((bounded.groupby("student_id").size() <= 2).all())

    def test_group_split_has_no_student_overlap(self):
        df = pd.DataFrame({
            "student_id": ["A", "A", "B", "B", "C", "D"],
            "score": [1, 2, 3, 4, 5, 6],
        })

        train, test = group_split_by_student(df, "student_id", test_size=0.5, seed=7)

        self.assertEqual(set(train["student_id"].unique()) & set(test["student_id"].unique()), set())

    def test_delta_validation_rejects_invalid_value(self):
        with self.assertRaises(ValueError):
            estimate_delta(1000, delta=0.2)

    def test_suggest_noise_multiplier_returns_positive_value(self):
        value = suggest_noise_multiplier(epsilon=2.0, delta=1e-5, sample_rate=0.1, epochs=20)
        self.assertGreater(value, 0.0)

    def test_budget_cap_enforcement_raises(self):
        with self.assertRaises(BudgetLedgerCapError):
            from lab.services.dp_accounting import BudgetLedger
            total = 2.0
            BudgetLedger.enforce_cap(1.0, total, 1.5)
