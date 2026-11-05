"""Provider isolation and Claude wire protocol; no paid API calls."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from promptcoach.config import PROVIDERS, Settings
from promptcoach.evaluation.ai import AIEvaluator
from promptcoach.evaluation.contracts import EVALUATION_SCHEMA, EvaluationError, validate_evaluation, validate_support
from promptcoach.evaluation.local import LocalEvaluator
from promptcoach.repository import Repository
from promptcoach.service import CoachService

TEXT = "Python 환경에서 CSV 분석기를 구현해줘. 표로 출력하고 기존 API는 유지해줘. 빈 파일 테스트로 검증해줘."


def claude_response(result, stop_reason="end_turn"):
    return io.BytesIO(json.dumps({"stop_reason": stop_reason, "content": [
        {"type": "thinking", "thinking": "ignored"},
        {"type": "text", "text": json.dumps(result, ensure_ascii=False)},
    ]}).encode())


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "", "PROMPTCOACH_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        self.settings = Settings(self.temp.name)

    def test_keys_are_isolated_by_provider_and_destination(self):
        self.settings.update({"provider": "openai", "api_key": "openai-test"})
        self.assertEqual(self.settings.snapshot()[1], "openai-test")
        result = self.settings.update({"provider": "anthropic"})
        self.assertEqual(result["base_url"], PROVIDERS["anthropic"]["base_url"])
        self.assertFalse(result["api_key_configured"])
        self.settings.update({"api_key": "claude-test"})
        self.settings.update({"provider": "openai"})
        self.assertEqual(self.settings.snapshot()[1], "openai-test")
        self.settings.update({"base_url": "https://other.example/v1"})
        self.assertEqual(self.settings.snapshot()[1], "")
        self.settings.update({"api_key": "other-test"})
        self.settings.update({"base_url": PROVIDERS["openai"]["base_url"] + "/"})
        self.assertEqual(self.settings.snapshot()[1], "openai-test")
        self.settings.update({"provider": "anthropic", "clear_key": True})
        self.assertEqual(self.settings.snapshot()[1], "")
        self.settings.update({"provider": "openai"})
        self.assertEqual(self.settings.snapshot()[1], "openai-test")

    def test_secrets_are_never_persisted_and_reset_after_restart(self):
        self.settings.update({"provider": "anthropic", "api_key": "private-test-secret"})
        saved = self.settings.path.read_text(encoding="utf-8")
        self.assertNotIn("private-test-secret", saved)
        self.assertNotIn("api_key", saved)
        self.assertNotIn("private-test-secret", json.dumps(self.settings.public()))
        reopened = Settings(self.temp.name)
        self.assertEqual(reopened.public()["provider"], "anthropic")
        self.assertFalse(reopened.public()["api_key_configured"])

    def test_environment_keys_only_apply_to_their_own_official_endpoint(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-env", "ANTHROPIC_API_KEY": "claude-env"}):
            settings = Settings(self.temp.name)
        settings.update({"provider": "anthropic"})
        self.assertEqual(settings.snapshot()[1], "claude-env")
        settings.update({"provider": "openai"})
        self.assertEqual(settings.snapshot()[1], "openai-env")
        settings.update({"base_url": "https://custom.example/v1"})
        self.assertEqual(settings.snapshot()[1], "")

    def test_existing_flat_settings_are_supported(self):
        values = {"provider": "openai", "model": "my-model", "base_url": "https://custom.example/v1", "timeout": 30}
        self.settings.path.write_text(json.dumps(values), encoding="utf-8")
        self.assertEqual(Settings(self.temp.name).snapshot()[0], values)

    def test_claude_endpoint_must_use_https_without_embedded_credentials(self):
        for url in ("http://api.anthropic.com/v1", "https://key@api.anthropic.com/v1", "https://api.anthropic.com/v1?key=secret"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.settings.update({"provider": "anthropic", "base_url": url})


class ClaudeTransportTests(unittest.TestCase):
    def setUp(self):
        self.adapter = AIEvaluator({"provider": "anthropic", "model": "test-model", "base_url": "https://api.anthropic.com/v1", "timeout": 10}, "claude-test")
        self.raw = LocalEvaluator().evaluate(TEXT, "", "development")

    def test_evaluation_headers_schema_and_response(self):
        with patch("promptcoach.evaluation.ai.urlopen", return_value=claude_response(self.raw)) as call:
            result = validate_evaluation(self.adapter.evaluate(TEXT, "배경 자료", "development"), TEXT)
        self.assertLessEqual(result["score"], 100)
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.get_header("X-api-key"), "claude-test")
        self.assertEqual(request.get_header("Anthropic-version"), "2026-10-21")
        self.assertIsNone(request.get_header("Authorization"))
        body = json.loads(request.data)
        self.assertEqual([m["role"] for m in body["messages"]], ["user"])
        self.assertIn("사전 평가자", body["system"])
        self.assertEqual(json.loads(body["messages"][0]["content"])["prompt"], TEXT)
        self.assertGreater(body["max_tokens"], 0)
        score = body["output_config"]["format"]["schema"]["properties"]["dimensions"]["items"]["properties"]["score"]
        self.assertNotIn("minimum", score)
        self.assertNotIn("maximum", score)
        self.assertEqual(EVALUATION_SCHEMA["properties"]["dimensions"]["items"]["properties"]["score"]["maximum"], 5)

    def test_support_uses_the_same_transport_with_support_schema(self):
        raw = {"clarifications": [{"topic": "입력 파일 형식", "reason": "입력 형식 확인", "question": "입력 필드는 무엇인가요?"}]}
        expected = {"improved_prompt": TEXT + "\n\n[직접 입력: 입력 파일 형식]", "changes": ["입력 형식 확인"], "questions": ["입력 필드는 무엇인가요?"], "clarifications": raw["clarifications"]}
        record = {"text": TEXT, "context": "배경", "result": self.raw}
        with patch("promptcoach.evaluation.ai.urlopen", return_value=claude_response(raw)) as call:
            self.assertEqual(validate_support(self.adapter.support(record)), expected)
        body = json.loads(call.call_args.args[0].data)
        self.assertIn("clarifications", body["output_config"]["format"]["schema"]["properties"])

    def test_refusal_truncation_and_invalid_json_are_rejected(self):
        for reason in ("refusal", "max_tokens", "tool_use", None):
            with self.subTest(reason=reason), patch("promptcoach.evaluation.ai.urlopen", return_value=claude_response(self.raw, reason)), self.assertRaises(EvaluationError):
                self.adapter.evaluate(TEXT, "", "auto")
        for payload in (b"[]", b"not-json", b'{"stop_reason":"end_turn","content":[]}', b'{"stop_reason":"end_turn","content":[{}]}'):
            with self.subTest(payload=payload), patch("promptcoach.evaluation.ai.urlopen", return_value=io.BytesIO(payload)), self.assertRaises(EvaluationError):
                self.adapter.evaluate(TEXT, "", "auto")

    def test_api_failures_and_missing_key_are_clear_errors(self):
        self.adapter.key = ""
        with self.assertRaisesRegex(EvaluationError, "ANTHROPIC_API_KEY"):
            self.adapter.evaluate(TEXT, "", "auto")
        self.adapter.key = "claude-test"
        for error in (HTTPError("https://example.invalid", 401, "private-test-secret", {}, None), URLError("offline")):
            with patch("promptcoach.evaluation.ai.urlopen", side_effect=error), self.assertRaises(EvaluationError) as caught:
                self.adapter.evaluate(TEXT, "", "auto")
            self.assertNotIn("private-test-secret", str(caught.exception))


class ClaudeServiceTests(unittest.TestCase):
    def test_consent_evaluate_support_and_failure_preserve_history(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(directory)
            settings.update({"provider": "anthropic", "api_key": "test-key"})
            repo = Repository(Path(directory) / "coach.sqlite3")
            service = CoachService(repo, settings)
            boot = service.bootstrap()
            self.assertIn("anthropic", boot["providers"])
            session = service.create("sessions", {"name": "Claude 연습", "project_id": boot["projects"][0]["id"], "member_id": boot["members"][0]["id"]})
            payload = {"text": TEXT, "session_id": session["id"], "request_id": "claude-1"}
            with self.assertRaises(ValueError):
                service.evaluate(payload)
            with patch("promptcoach.evaluation.ai.urlopen", return_value=claude_response(LocalEvaluator().evaluate(TEXT, "", "auto"))):
                record = service.evaluate({**payload, "allow_remote": True})
            self.assertTrue(record["engine"].startswith("anthropic:"))
            with self.assertRaises(ValueError):
                service.support({"prompt_id": record["id"]})
            support = {"clarifications": []}
            with patch("promptcoach.evaluation.ai.urlopen", return_value=claude_response(support)):
                result = service.support({"prompt_id": record["id"], "allow_remote": True})
            self.assertEqual(result["engine"], record["engine"])
            self.assertEqual(repo.get(record["id"])["text"], TEXT)
            for raw in (claude_response({}, "refusal"), claude_response({"summary": "invalid"})):
                with patch("promptcoach.evaluation.ai.urlopen", return_value=raw), self.assertRaises(EvaluationError):
                    service.evaluate({**payload, "request_id": "failed", "allow_remote": True})
            self.assertEqual(service.history({})["summary"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
