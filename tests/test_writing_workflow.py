"""Writing and Support must not depend on grading or an arbitrary prompt length."""
import json
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from promptcoach.config import Settings
from promptcoach.evaluation.ai import AIEvaluator
from promptcoach.evaluation.contracts import validate_evaluation, validate_support
from promptcoach.evaluation.local import LocalEvaluator
from promptcoach.repository import Repository
from promptcoach.server import create_server
from promptcoach.service import CoachService

TEXT = "Python 환경에서 CSV를 분석해줘. 기존 API를 유지하고 결과를 표로 보여줘. 빈 파일 테스트로 검증해줘."


class WritingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Repository(Path(self.temp.name) / "coach.sqlite3")
        self.settings = Settings(self.temp.name)
        self.service = CoachService(self.repo, self.settings)

    def test_support_without_evaluation_or_session_makes_one_ai_call(self):
        self.settings.update({"provider": "ollama"})
        project = self.service.create("projects", {"name": "실제 프로젝트", "guidelines": "Windows 환경 유지"})
        raw = {"improved_prompt": TEXT, "changes": ["요구사항을 유지했습니다."], "questions": []}
        with patch.object(AIEvaluator, "evaluate", side_effect=AssertionError("grading must not run")), patch.object(AIEvaluator, "support", return_value=raw) as call:
            result = self.service.support({"text": TEXT, "project_id": project["id"]})
        self.assertEqual(call.call_count, 1)
        self.assertIn("Windows 환경 유지", call.call_args.args[0]["context"])
        self.assertFalse(result["stored"])
        self.assertEqual(result["improved_prompt"], TEXT)
        self.assertEqual(self.repo.history({}), [])

    def test_local_support_without_a_score_record(self):
        result = self.service.support({"text": "파이썬으로 파일 분석기를 만들어줘."})
        self.assertTrue(result["improved_prompt"])
        self.assertEqual(self.repo.history({}), [])

    def test_qwen3_support_requests_fast_mode_without_grading_payload(self):
        evaluator = AIEvaluator({"provider": "ollama", "model": "qwen3:8b-q4_K_M", "base_url": "http://127.0.0.1:11434", "timeout": 10}, "")
        raw = {"clarifications": []}
        response = io.BytesIO(json.dumps({"message": {"content": json.dumps(raw)}}).encode())
        with patch("promptcoach.evaluation.ai.urlopen", return_value=response) as call:
            evaluator.support({"text": TEXT, "context": "", "result": {}})
        body = json.loads(call.call_args.args[0].data)
        self.assertIs(body["think"], False)
        payload = json.loads(body["messages"][1]["content"])
        self.assertNotIn("evaluation", payload)
        self.assertNotIn("rubric", payload)

    def test_optional_evaluation_without_session_does_not_create_history(self):
        result = self.service.evaluate({"text": TEXT, "request_id": "optional"})
        self.assertFalse(result["stored"])
        self.assertEqual(result["text"], TEXT)
        self.assertIn(result["grade"], ("good", "normal", "bad"))
        self.assertEqual(self.repo.history({}), [])

    def test_long_prompt_context_and_whitespace_are_preserved(self):
        text = "\n  " + TEXT * 800 + "\n\n"
        context = "프로젝트 자료\n" * 2000
        result = self.service.evaluate({"text": text, "context": context, "request_id": "long"})
        self.assertEqual(result["text"], text)
        self.assertEqual(result["context"], context)
        raw = {"improved_prompt": text, "changes": [], "questions": []}
        self.assertEqual(validate_support(raw)["improved_prompt"], text)

    def test_unverified_technique_is_a_candidate_not_a_fatal_error(self):
        raw = LocalEvaluator().evaluate(TEXT, "", "auto")
        raw["techniques"][0]["evidence"] = "AI가 요약한 문구"
        result = validate_evaluation(raw, TEXT)
        self.assertFalse(result["techniques"][0]["evidence_verified"])
        verified = [d for d in result["dimensions"] if d["evidence"]]
        self.assertTrue(all(d["evidence_verified"] for d in verified))

    def test_http_support_accepts_large_multilingual_draft_without_session(self):
        server = create_server(self.temp.name, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            text = TEXT * 1000
            body = json.dumps({"text": text}).encode()
            self.assertGreater(len(body), 180000)
            request = Request(f"http://127.0.0.1:{server.server_port}/api/support", data=body,
                              headers={"Content-Type": "application/json", "X-Prompt-Coach": "1"})
            with urlopen(request, timeout=5) as response:
                result = json.load(response)
            self.assertTrue(result["improved_prompt"].startswith(text))
            self.assertFalse(result["stored"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
