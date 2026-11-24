import json
import csv
from pathlib import Path
import tempfile
import unittest

import _bootstrap  # noqa: F401

from modelador.core import audit_model, canonical_cover, closure, parse_fds, synthesize_3nf
from modelador.evaluation import load_cases, run_benchmark, score
from modelador.agents import validate_dictionary_response
from modelador.pipeline import design
from modelador.adapters.base import LLMError


CASES = Path(__file__).parents[1] / "experiments" / "cases" / "reference.json"


class FakeOllama:
    model = "fake"

    def __init__(self, expected):
        self.expected = expected
        self.current = expected
        self.calls = 0

    def ask(self, system, user, schema=None):
        self.calls += 1
        if self.expected is None:
            for case in load_cases(CASES):
                if case["requirements"] in user:
                    self.current = case["expected"]
                    break
        expected = self.current
        if "agente de diccionario" in system:
            answer = {"columns": {a: {"type": "TEXT", "nullable": False, "description": a} for a in expected["attributes"]}}
        elif "agente codificador" in system:
            answer = {"column_types": {a: "TEXT" for a in expected["attributes"]}, "notes": []}
        elif "un solo agente" in system:
            tables = synthesize_3nf(expected["attributes"], parse_fds(expected["functional_dependencies"], expected["attributes"]))
            answer = {**expected, "tables": tables, "dictionary": [{"name": a, "type": "TEXT", "nullable": False, "description": a} for a in expected["attributes"]], "assumptions": []}
        else:
            answer = {**expected, "entities": [], "assumptions": []}
        return answer, {"eval_count": 1}


class NormalizationTests(unittest.TestCase):
    def test_generic_client_receives_schemas_and_progress(self):
        case = load_cases(CASES)[0]
        events = []

        class SchemaClient(FakeOllama):
            progress = events.append

            def ask(self, system, user, schema=None):
                if not schema or "required" not in schema:
                    raise AssertionError("Falta el esquema del agente")
                return super().ask(system, user, schema=schema)

        result = design(case["requirements"], SchemaClient(case["expected"]))
        self.assertEqual(result["status"], "ok", result.get("error"))
        self.assertEqual([event["event"] for event in events], ["started", "completed"] * 3)

    def test_generic_llm_error_is_reported(self):
        class BrokenClient:
            model = "fake"
            progress = None

            def ask(self, system, user, schema=None):
                raise LLMError("proveedor no disponible")

        result = design("Un requisito", BrokenClient())
        self.assertEqual(result["status"], "error")
        self.assertIn("proveedor no disponible", result["error"])

    def test_transitive_dependency_detected(self):
        attrs = ["student_id", "course_id", "professor_id", "professor_name"]
        fds = [{"determinant": ["student_id"], "dependent": ["course_id"]}, {"determinant": ["course_id"], "dependent": ["professor_id"]}, {"determinant": ["professor_id"], "dependent": ["professor_name"]}]
        bad = [{"name": "all_data", "columns": attrs, "primary_key": ["student_id"]}]
        self.assertFalse(audit_model(attrs, fds, bad)["valid_3nf"])

    def test_reference_cases_synthesize_and_verify(self):
        for case in load_cases(CASES):
            expected = case["expected"]
            attrs = expected["attributes"]
            fds = parse_fds(expected["functional_dependencies"], attrs)
            tables = synthesize_3nf(attrs, fds)
            audit = audit_model(attrs, expected["functional_dependencies"], tables)
            with self.subTest(case=case["id"]):
                self.assertTrue(audit["valid_3nf"], audit)
                self.assertFalse(audit["missing_attributes"])
                self.assertFalse(audit["unpreserved_dependencies"])
                self.assertTrue(audit["contains_candidate_key"])

    def test_full_pipeline_with_fake_local_model(self):
        case = load_cases(CASES)[0]
        for mode in ("multi", "single"):
            client = FakeOllama(case["expected"])
            result = design(case["requirements"], client, mode)
            with self.subTest(mode=mode):
                self.assertEqual(result["status"], "ok", result.get("error"))
                self.assertTrue(score(result, case["expected"])["success"])
                self.assertIn("CREATE TABLE", result["artifact"]["ddl"])
                self.assertEqual(client.calls, 3 if mode == "multi" else 1)

    def test_benchmark_exports_all_cases_and_modes(self):
        with tempfile.TemporaryDirectory() as path:
            first_rows, first_dir = run_benchmark(load_cases(CASES), path, FakeOllama(None))
            second_rows, second_dir = run_benchmark(load_cases(CASES), path, FakeOllama(None))
            rows = first_rows
            self.assertEqual(len(rows), 6)
            self.assertTrue(all(row["success"] for row in rows), rows)
            self.assertNotEqual(first_dir, second_dir)
            self.assertEqual(len(second_rows), 6)
            self.assertTrue((first_dir / "summary.csv").exists())
            self.assertTrue((second_dir / "summary.csv").exists())
            self.assertEqual(len(list(first_dir.glob("*.json"))), 6)
            self.assertEqual(len(list(second_dir.glob("*.json"))), 6)
            self.assertFalse((Path(path) / "summary.csv").exists())

    def test_echoed_input_is_rejected_then_corrected(self):
        case = load_cases(CASES)[0]

        class EchoFirst(FakeOllama):
            def ask(self, system, user, schema=None):
                if self.calls == 0:
                    self.calls += 1
                    return {"requirements": case["requirements"], "feedback": None}, {"eval_count": 10}
                return super().ask(system, user, schema=schema)

        client = EchoFirst(case["expected"])
        result = design(case["requirements"], client)
        self.assertEqual(result["status"], "ok", result.get("error"))
        self.assertEqual(client.calls, 4)
        rejected = result["trace"][0]
        self.assertEqual(rejected["status"], "rejected")
        self.assertIn("attributes", rejected["validation_error"])
        self.assertEqual(rejected["output"]["requirements"], case["requirements"])

    def test_retries_only_dictionary_stage(self):
        case = load_cases(CASES)[0]

        class BadDictionaryOnce(FakeOllama):
            def ask(self, system, user, schema=None):
                if "agente de diccionario" in system and not hasattr(self, "failed"):
                    self.failed = True
                    self.calls += 1
                    return {"columns": []}, {}
                return super().ask(system, user, schema=schema)

        client = BadDictionaryOnce(case["expected"])
        result = design(case["requirements"], client)
        self.assertEqual(result["status"], "ok", result.get("error"))
        self.assertEqual(client.calls, 4)
        self.assertEqual(len([x for x in result["trace"] if x.get("agent") == "analyst"]), 1)

    def test_three_observed_dictionary_shapes_report_missing_and_unknown_names(self):
        attrs = load_cases(CASES)[0]["expected"]["attributes"]
        observed = [
            ["course_id", "course_name", "professor_id", "grade", "student_id"],
            ["course_id", "course_name", "professor_id", "enrollment_course_id", "enrollment_grade", "enrollment_student_id", "professor_id", "professor_name", "student_id", "student_name"],
            ["course_id", "course_name", "professor_id", "student_id", "student_name", "grade"],
        ]
        for names_seen in observed:
            answer = {"columns": [{"name": name, "type": "TEXT", "nullable": False, "description": name} for name in names_seen]}
            with self.subTest(names=names_seen), self.assertRaisesRegex(ValueError, "columns debe ser un objeto") as caught:
                validate_dictionary_response(answer, attrs)
            self.assertIn("faltan atributos", str(caught.exception))
            self.assertIn("desconocidos", str(caught.exception))

    def test_dictionary_remains_strict_after_three_attempts(self):
        case = load_cases(CASES)[0]

        class MissingDescription(FakeOllama):
            def ask(self, system, user, schema=None):
                if "agente de diccionario" in system:
                    self.calls += 1
                    return {"columns": {name: {"type": "TEXT", "nullable": False, "description": name} for name in case["expected"]["attributes"] if name != "grade"}}, {}
                return super().ask(system, user, schema=schema)

        result = design(case["requirements"], MissingDescription(case["expected"]))
        self.assertEqual(result["status"], "error")
        self.assertIn("grade", result["error"])
        self.assertEqual(len([x for x in result["trace"] if x.get("agent") == "dictionary"]), 3)
        self.assertFalse(any(x.get("agent") == "coder" for x in result["trace"]))

    def test_echo_retry_limit_is_explicit(self):
        class AlwaysEcho:
            model = "fake"
            def ask(self, system, user, schema=None):
                return {"requirements": user, "feedback": None}, {}

        result = design("Un requisito", AlwaysEcho())
        self.assertEqual(result["status"], "error")
        self.assertIn("3 intentos", result["error"])
        self.assertIn("faltan campos", result["error"])
        self.assertEqual(len([x for x in result["trace"] if x.get("agent") == "analyst"]), 3)

    def test_invalid_coder_output_retries_only_coder(self):
        case = load_cases(CASES)[0]

        class BadCoderOnce(FakeOllama):
            def ask(self, system, user, schema=None):
                if "agente codificador" in system and not hasattr(self, "failed"):
                    self.failed = True
                    self.calls += 1
                    return {"column_types": {"student_id": "MYSTERY"}, "notes": []}, {}
                return super().ask(system, user, schema=schema)

        client = BadCoderOnce(case["expected"])
        result = design(case["requirements"], client)
        self.assertEqual(result["status"], "ok", result.get("error"))
        self.assertEqual(client.calls, 4)
        self.assertEqual(len([x for x in result["trace"] if x.get("agent") == "dictionary"]), 1)

    def test_single_agent_echo_has_clear_error_without_retry(self):
        class AlwaysEcho:
            model = "fake"
            def ask(self, system, user, schema=None):
                return {"requirements": user}, {}

        result = design("Un requisito", AlwaysEcho(), mode="single")
        self.assertEqual(result["status"], "error")
        self.assertIn("faltan campos", result["error"])
        self.assertEqual(result["trace"][0]["status"], "rejected")

    def test_captured_failure_recovers_ddl_and_marks_benchmark(self):
        case = load_cases(CASES)[0]

        class CapturedFailure(FakeOllama):
            def __init__(self, expected):
                super().__init__(expected)
                self.dictionary_attempts = 0

            def ask(self, system, user, schema=None):
                if "agente de diccionario" in system:
                    self.dictionary_attempts += 1
                    if self.dictionary_attempts == 1:
                        self.calls += 1
                        return {"columns": [{"name": "atributo", "type": "TEXT", "nullable": False, "description": "..."}]}, {}
                if "agente codificador" in system:
                    self.calls += 1
                    return {"column_types": {"atributo": "TEXT"}, "notes": []}, {}
                answer, usage = super().ask(system, user, schema=schema)
                if "Extrae atributos atómicos" in system:
                    answer["entities"] = [{"name": "Student", "attributes": ["student_id", "student_name"]}]
                return answer, usage

        client = CapturedFailure(case["expected"])
        result = design(case["requirements"], client)
        self.assertEqual(result["status"], "ok", result.get("error"))
        artifact = result["artifact"]
        self.assertEqual(artifact["coder_status"], "fallback")
        self.assertIn("atributo", artifact["coder_error"])
        self.assertIn("CREATE TABLE student", artifact["ddl"])
        self.assertEqual(artifact["analysis"]["entity_name_changes"], [{"from": "Student", "to": "student"}])
        self.assertEqual(result["trace"][0]["output"]["entities"][0]["name"], "Student")
        self.assertTrue(score(result, case["expected"])["schema_success"])
        self.assertFalse(score(result, case["expected"])["full_agent_success"])
        with tempfile.TemporaryDirectory() as path:
            rows, run_dir = run_benchmark([case], path, CapturedFailure(case["expected"]))
            self.assertEqual(rows[0]["coder_status"], "fallback")
            self.assertFalse(rows[0]["full_agent_success"])
            with (run_dir / "summary.csv").open(encoding="utf-8") as handle:
                first = next(csv.DictReader(handle))
            self.assertEqual(first["coder_status"], "fallback")
            self.assertEqual(first["full_agent_success"], "False")


if __name__ == "__main__":
    unittest.main()
