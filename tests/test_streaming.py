import json
import sys
import tempfile
from pathlib import Path
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from unittest.mock import patch

from modelador.cli import main
from modelador.pipeline import ANALYST_SCHEMA, Ollama, OllamaError, design


class StreamingTests(unittest.TestCase):
    def test_streamed_json_and_options(self):
        script = """import json,sys,time
data=json.loads(sys.stdin.readline())
assert data['payload']['stream'] is True
assert data['payload']['think'] is False
assert data['payload']['format']['required']==['attributes','functional_dependencies','entities','assumptions']
print(json.dumps({'event':'chunk','content':'{"answer":'}),flush=True)
print(json.dumps({'event':'chunk','content':'1}'}),flush=True)
print(json.dumps({'event':'done','usage':{'eval_count':2}}),flush=True)
"""
        client = Ollama(timeout=2, worker_command=[sys.executable, "-c", script])
        answer, usage = client.ask("system", "user", ANALYST_SCHEMA)
        self.assertEqual(answer, {"answer": 1})
        self.assertEqual(usage["eval_count"], 2)

    def test_deadline_preserves_partial_response(self):
        script = """import json,sys,time
sys.stdin.readline()
print(json.dumps({'event':'chunk','content':'{"unfinished":'}),flush=True)
time.sleep(5)
"""
        client = Ollama(timeout=0.3, worker_command=[sys.executable, "-c", script])
        with self.assertRaises(OllamaError) as caught:
            client.ask("system", "user")
        self.assertIn("límite", str(caught.exception))
        self.assertEqual(caught.exception.partial, '{"unfinished":')

    def test_pipeline_passes_each_agent_schema_to_worker(self):
        script = """import json,sys
data=json.loads(sys.stdin.readline())
required=set(data['payload']['format']['required'])
if 'entities' in required:
    answer={'attributes':['student_id','student_name'],'functional_dependencies':[{'determinant':['student_id'],'dependent':['student_name']}],'entities':[],'assumptions':[]}
elif 'columns' in required:
    assert set(data['payload']['format']['properties']['columns']['required'])=={'student_id','student_name'}
    assert data['payload']['format']['properties']['columns']['additionalProperties'] is False
    answer={'columns':{name:{'type':'TEXT','nullable':False,'description':name} for name in ('student_id','student_name')}}
elif 'column_types' in required:
    assert set(data['payload']['format']['properties']['column_types']['required'])=={'student_id','student_name'}
    assert data['payload']['format']['properties']['column_types']['additionalProperties'] is False
    answer={'column_types':{'student_id':'TEXT','student_name':'TEXT'},'notes':[]}
else:
    raise SystemExit(2)
print(json.dumps({'event':'chunk','content':json.dumps(answer)}),flush=True)
print(json.dumps({'event':'done','usage':{'eval_count':1}}),flush=True)
"""
        client = Ollama(timeout=2, worker_command=[sys.executable, "-c", script])
        result = design("student_id determina student_name", client)
        self.assertEqual(result["status"], "ok", result.get("error"))
        self.assertEqual([item["agent"] for item in result["trace"]], ["analyst", "dictionary", "coder"])

    def test_cancelled_design_has_no_traceback_and_keeps_trace(self):
        class InterruptingClient:
            model = "fake"

            def ask(self, system, user):
                raise KeyboardInterrupt()

        result = design("Un requisito", InterruptingClient())
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["trace"][0]["status"], "cancelled")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "requirements.txt"
            source.write_text("Un requisito", encoding="utf-8")
            output = StringIO()
            errors = StringIO()
            with patch("modelador.cli.Ollama", return_value=InterruptingClient()), redirect_stdout(output), redirect_stderr(errors):
                code = main(["design", str(source), "--output", directory])
            self.assertEqual(code, 130)
            self.assertNotIn("Traceback", errors.getvalue())
            saved = next(Path(directory).glob("design_*.json"))
            self.assertEqual(json.loads(saved.read_text(encoding="utf-8"))["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
