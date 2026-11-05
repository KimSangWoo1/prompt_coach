"""Transparent deterministic practice checks. This is NOT AI grading."""
import re
from ..catalog import TECHNIQUES, DIMENSIONS
from .contracts import validate_evaluation

class LocalEvaluator:
    label = "local:rules-1.0"

    def evaluate(self, text, context, task):
        combined = text + "\n" + context
        low = combined.lower()
        found = []
        for tid, name, desc, when, limitation, patterns in TECHNIQUES:
            for p in patterns:
                match = re.search(re.escape(p), combined, re.I)
                if match:
                    found.append({"id": tid, "evidence": match.group(), "explanation": f"‘{match.group()}’ 표현을 확인했습니다. 의미와 실제 실행 여부는 이 규칙으로 확정할 수 없습니다."})
                    break
        # A keyword does not prove a complete input/output example.
        found_ids = {x["id"] for x in found}
        if "few_shot" in found_ids:
            found = [x for x in found if x["id"] != "one_shot"]
        if not found_ids.intersection({"one_shot", "few_shot"}):
            found.append({"id": "zero_shot", "evidence": text[:100], "explanation": "예시 표지를 찾지 못한 Zero-shot 후보입니다. 표지 없이 적은 예시를 놓칠 수 있습니다."})
        has = lambda tid: tid in {x["id"] for x in found}
        simple = task == "simple" or (task == "auto" and any(w in low for w in ("번역", "translate", "한 문장", "한 줄", "뜻", "meaning")) and not any(w in low for w in ("구현", "설계", "프로젝트")))
        action = bool(re.search(r"작성|구현|설명|분석|정리|찾아|수정|번역|요약|만들|알려|계산|비교|write|create|explain|fix|translate|summar", low))
        meaningful = len(re.sub(r"\s", "", text)) >= 12
        scores = {"clarity": 4 if action and meaningful else 2 if action else 1,
                  "context": 4 if context.strip() or has("context") else 1,
                  "constraints": 4 if has("constraints") else 1,
                  "output": 4 if has("output") else 2,
                  "verification": 4 if has("criteria") else 1,
                  "examples": 4 if has("one_shot") or has("few_shot") else 1}
        if simple and action and meaningful:
            scores["clarity"] = 5
            if has("output"):
                scores["output"] = 5
        if re.search(r"\[\s*직접\s*입력\s*:", text):
            # Support placeholders are unanswered questions, not fulfilled requirements.
            scores = {k: min(v, 2) for k, v in scores.items()}
        reasons = {
            "clarity": "작업 동사와 대상이 있는지 점검합니다. 실제 의미와 모순 여부는 AI 평가로 확인하세요.",
            "context": "관련 환경 표현 또는 별도 배경 자료의 존재를 점검합니다.",
            "constraints": "범위·금지·유지 조건을 나타내는 표현의 존재를 점검합니다.",
            "output": "출력 형식을 나타내는 표현의 존재를 점검합니다.",
            "verification": "검증·테스트·완료 조건 표현의 존재를 점검합니다.",
            "examples": "예시 표지를 점검합니다. 예시의 품질을 판단하지는 못합니다."}
        suggestions = {"clarity": "요청하는 작업, 대상, 기대하는 변화를 명확히 적어 주세요.",
            "context": "필요한 환경·현재 상황·참고 자료를 추가해 주세요.",
            "constraints": "변경 범위와 유지해야 할 조건을 구체적으로 적어 주세요.",
            "output": "원하는 결과물의 형식과 상세 수준을 적어 주세요.",
            "verification": "성공 여부를 확인할 관찰 가능한 조건을 적어 주세요.",
            "examples": "고유한 형식이 중요하다면 입력과 모범 결과 예시를 제공해 주세요."}
        needs_examples = any(w in low for w in ("같은 형식", "동일한 스타일", "분류", "스타일을", "same format"))
        dims = []
        for did in DIMENSIONS:
            applicable = did in ("clarity", "output") or (not simple and (did != "examples" or needs_examples))
            evidence = next((t["evidence"] for t in found if t["id"] == {"verification": "criteria", "examples": "one_shot", "clarity": "none"}.get(did, did)), "")
            dims.append({"id": did, "applicable": applicable, "score": scores[did],
                         "reason": reasons[did] if applicable else "이 작업에서 필수 요소로 보지 않아 총점 계산에서 제외했습니다.",
                         "evidence": evidence, "improvement": suggestions[did] if applicable and scores[did] < 4 else ""})
        mapping = {"clarity": "decomposition", "context": "context", "constraints": "constraints", "output": "output", "verification": "criteria", "examples": "few_shot"}
        recs = [{"id": mapping[d["id"]], "reason": d["improvement"], "example": suggestions[d["id"]]} for d in dims if d["applicable"] and d["score"] < 4]
        return {"summary": "규칙 기반 사전 점검입니다. 표현의 존재를 확인하는 학습 보조 지표이며 AI의 의미 평가가 아닙니다.",
            "dimensions": dims, "techniques": found, "recommendations": recs[:4],
            "strengths": [f"{DIMENSIONS[d['id']][0]} 관련 표현을 포함했습니다." for d in dims if d["applicable"] and d["score"] >= 4],
            "questions": [d["improvement"] for d in dims if d["applicable"] and d["score"] < 4][:4]}

    def support(self, record):
        result = record["result"]
        if "dimensions" not in result:
            result = validate_evaluation(self.evaluate(record["text"], record["context"], record["task"]), record["text"], record["context"])
        missing = [d for d in result["dimensions"] if d["applicable"] and d["score"] < 4]
        additions = []
        for d in missing:
            additions.append(f"{d['label']}\n[직접 입력: {d['improvement']}]")
        return {"improved_prompt": record["text"] + ("\n\n" + "\n\n".join(additions) if additions else ""),
            "changes": [f"{d['label']} 보완을 위한 빈칸을 추가했습니다. 실제 요구는 직접 채워 주세요." for d in missing] or ["규칙상 큰 누락이 없어 원문을 유지했습니다. 의미 평가는 AI 모드에서 확인할 수 있습니다."],
            "questions": result["questions"]}
