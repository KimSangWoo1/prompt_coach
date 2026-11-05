"""Clarification-only Support preserves the user's text and bounds extra work."""
import unittest
from unittest.mock import patch

from promptcoach.evaluation.ai import AIEvaluator
from promptcoach.evaluation.contracts import EvaluationError


class SupportRefinementTests(unittest.TestCase):
    def setUp(self):
        self.adapter = AIEvaluator({"provider": "ollama", "model": "test"}, "")
        self.text = "\n유니티 UIManager 초안을 만들어줘. 기존 API와 인벤토리 열기/닫기만 유지해.\n"
        self.record = {"text": self.text, "context": "uGUI 사용. 새 기능 추가 금지.", "task": "development"}
        self.item = {"topic": "관리할 UI 종류", "reason": "대상에 따라 초안이 달라집니다.", "question": "어떤 UI를 관리하나요?"}

    def test_model_cannot_rewrite_or_drop_original_requirements(self):
        raw = {"clarifications": [self.item], "improved_prompt": "원문을 버리고 싱글턴과 이벤트 버스를 구현해줘."}
        with patch.object(self.adapter, "call", return_value=raw):
            result = self.adapter.support(self.record)
        self.assertTrue(result["improved_prompt"].startswith(self.text))
        self.assertNotIn("싱글턴", result["improved_prompt"])
        self.assertNotIn("이벤트 버스", result["improved_prompt"])
        self.assertIn("[직접 입력: 관리할 UI 종류]", result["improved_prompt"])
        self.assertEqual(result["questions"], [self.item["question"]])

    def test_clear_request_returns_original_without_cosmetic_rewriting(self):
        with patch.object(self.adapter, "call", return_value={"clarifications": []}):
            result = self.adapter.support(self.record)
        self.assertEqual(result, {"improved_prompt": self.text, "changes": [], "questions": []})

    def test_only_two_clarifications_are_shown(self):
        raw = {"clarifications": [{**self.item, "topic": str(i)} for i in range(4)]}
        with patch.object(self.adapter, "call", return_value=raw):
            result = self.adapter.support(self.record)
        self.assertEqual(len(result["questions"]), 2)
        self.assertEqual(result["improved_prompt"].count("[직접 입력:"), 2)

    def test_project_context_is_passed_without_an_extra_ai_evaluation(self):
        with patch.object(self.adapter, "call", return_value={"clarifications": []}) as call:
            self.adapter.support(self.record)
        self.assertEqual(call.call_count, 1)
        payload = call.call_args.args[1]
        self.assertEqual(payload["context"], self.record["context"])
        self.assertEqual(payload["prompt"], self.text)
        self.assertNotIn("evaluation", payload)

    def test_invalid_model_shape_does_not_fabricate_an_improvement(self):
        for raw in (None, [], {}, {"clarifications": "invalid"}, {"clarifications": [None]}):
            with self.subTest(raw=raw), patch.object(self.adapter, "call", return_value=raw), self.assertRaises(EvaluationError):
                self.adapter.support(self.record)


if __name__ == "__main__":
    unittest.main()
