import math
from ..catalog import DIMENSIONS, TECHNIQUE_IDS, RUBRIC_VERSION, grade

class EvaluationError(ValueError):
    pass

def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

S = {"type": "string"}
STRINGS = {"type": "array", "items": S}
DIM_SCHEMA = obj({"id": {"type": "string", "enum": list(DIMENSIONS)}, "applicable": {"type": "boolean"},
    "score": {"type": "integer", "minimum": 0, "maximum": 5}, "reason": S, "evidence": S, "improvement": S})
TECH_SCHEMA = obj({"id": {"type": "string", "enum": sorted(TECHNIQUE_IDS)}, "evidence": S, "explanation": S})
RECOMMEND_SCHEMA = obj({"id": {"type": "string", "enum": sorted(TECHNIQUE_IDS)}, "reason": S, "example": S})
EVALUATION_SCHEMA = obj({"summary": S, "dimensions": {"type": "array", "items": DIM_SCHEMA},
    "techniques": {"type": "array", "items": TECH_SCHEMA},
    "recommendations": {"type": "array", "items": RECOMMEND_SCHEMA}, "strengths": STRINGS, "questions": STRINGS})
SUPPORT_SCHEMA = obj({"improved_prompt": S, "changes": STRINGS, "questions": STRINGS})
CLARIFICATION_SCHEMA = obj({"clarifications": {"type": "array", "items": obj({"topic": S, "reason": S, "question": S})}})
SUPPORT_SCHEMA["properties"]["clarifications"] = {**CLARIFICATION_SCHEMA["properties"]["clarifications"], "maxItems": 2}

def string(value, name, limit=3000):
    if not isinstance(value, str) or (limit is not None and len(value) > limit):
        raise EvaluationError(f"평가 응답의 {name} 형식이 올바르지 않습니다.")
    return value

def string_list(value, name):
    if not isinstance(value, list) or len(value) > 20:
        raise EvaluationError(f"평가 응답의 {name} 목록이 올바르지 않습니다.")
    return [string(s, name) for s in value]

def validate_evaluation(raw, text, context=""):
    """Treat LLM output as untrusted; recompute total using the server rubric."""
    if not isinstance(raw, dict):
        raise EvaluationError("평가 결과는 JSON 객체여야 합니다.")
    result = {"summary": string(raw.get("summary"), "summary"), "dimensions": [], "techniques": [], "recommendations": []}
    dims = raw.get("dimensions")
    if not isinstance(dims, list) or len(dims) != len(DIMENSIONS):
        raise EvaluationError("6개 평가 항목이 모두 필요합니다.")
    seen = set()
    source = text + "\n" + context
    for d in dims:
        if not isinstance(d, dict) or d.get("id") not in DIMENSIONS or d["id"] in seen:
            raise EvaluationError("평가 항목이 중복되었거나 알 수 없는 항목입니다.")
        seen.add(d["id"])
        if type(d.get("score")) is not int or not 0 <= d["score"] <= 5 or type(d.get("applicable")) is not bool:
            raise EvaluationError("항목 점수 또는 적용 여부가 올바르지 않습니다.")
        if d["id"] == "clarity" and not d["applicable"]:
            raise EvaluationError("목표 명확성은 필수 평가 항목입니다.")
        item = {"id": d["id"], "applicable": d["applicable"], "score": d["score"]}
        for key in ("reason", "evidence", "improvement"):
            item[key] = string(d.get(key, ""), key)
        item["evidence_verified"] = bool(item["evidence"] and item["evidence"] in source)
        if not item["reason"].strip():
            raise EvaluationError("항목별 판단 근거가 필요합니다.")
        item.update(label=DIMENSIONS[d["id"]][0], weight=DIMENSIONS[d["id"]][1])
        result["dimensions"].append(item)
    for key in ("techniques", "recommendations"):
        values = raw.get(key)
        if not isinstance(values, list) or len(values) > 17:
            raise EvaluationError("기법 목록 형식이 올바르지 않습니다.")
        ids = set()
        for t in values:
            if not isinstance(t, dict) or t.get("id") not in TECHNIQUE_IDS or t["id"] in ids:
                raise EvaluationError("알 수 없거나 중복된 기법입니다.")
            ids.add(t["id"])
            fields = ("evidence", "explanation") if key == "techniques" else ("reason", "example")
            item = {"id": t["id"], **{k: string(t.get(k, ""), k) for k in fields}}
            if key == "techniques":
                item["evidence_verified"] = bool(item["evidence"] and item["evidence"] in source)
            result[key].append(item)
    for key in ("strengths", "questions"):
        result[key] = string_list(raw.get(key), key)
    relevant = [d for d in result["dimensions"] if d["applicable"]]
    score = round(sum(d["score"] / 5 * d["weight"] for d in relevant) / sum(d["weight"] for d in relevant) * 100, 1)
    if not math.isfinite(score):
        raise EvaluationError("유효한 점수가 아닙니다.")
    result.update(score=score, grade=grade(score), rubric=RUBRIC_VERSION)
    return result

def validate_support(raw):
    if not isinstance(raw, dict):
        raise EvaluationError("개선 결과가 JSON 객체가 아닙니다.")
    prompt = string(raw.get("improved_prompt"), "improved_prompt", None)
    if not prompt.strip():
        raise EvaluationError("개선 프롬프트가 비어 있습니다.")
    result = {"improved_prompt": prompt, "changes": string_list(raw.get("changes"), "changes"),
              "questions": string_list(raw.get("questions"), "questions")}
    if "clarifications" in raw:
        items = raw["clarifications"]
        if not isinstance(items, list) or len(items) > 2 or any(not isinstance(item, dict) for item in items):
            raise EvaluationError("보완 항목 목록 형식이 올바르지 않습니다.")
        result["clarifications"] = [{key: string(item.get(key), key) for key in ("topic", "reason", "question")} for item in items]
        if any(not value.strip() for item in result["clarifications"] for value in item.values()):
            raise EvaluationError("보완 항목 내용이 비어 있습니다.")
    return result
