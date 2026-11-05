import json
from .config import PROVIDERS
from .examples import EXAMPLES
from collections import Counter, defaultdict
from .catalog import DIMENSIONS, RUBRIC_VERSION, catalog
from .evaluation.local import LocalEvaluator
from .evaluation.ai import AIEvaluator
from .evaluation.contracts import validate_evaluation, validate_support, EvaluationError

def text_field(data, key, limit=200, required=True, strip=True):
    value = data.get(key, "")
    if not isinstance(value, str) or (limit is not None and len(value) > limit) or (required and not value.strip()):
        message = f"{key}: 내용을 확인해 주세요."
        if limit is not None: message += f" 최대 {limit:,}자입니다."
        raise ValueError(message)
    return value.strip() if strip else value

class CoachService:
    def __init__(self, repository, settings):
        self.repo, self.settings = repository, settings

    def evaluator(self, allow_remote=False):
        values, key = self.settings.snapshot()
        if values["provider"] in ("openai", "anthropic") and allow_remote is not True:
            raise ValueError("외부 API 전송 동의를 선택해 주세요. 프롬프트와 배경·프로젝트 규칙이 설정한 API로 전송됩니다.")
        return LocalEvaluator() if values["provider"] == "local" else AIEvaluator(values, key)

    def bootstrap(self):
        return {**self.repo.bootstrap(), "settings": self.settings.public(), "providers": PROVIDERS, "techniques": catalog(), "examples": EXAMPLES,
                "rubric": RUBRIC_VERSION, "dimensions": {k: {"label": v[0], "weight": v[1], "description": v[2]} for k, v in DIMENSIONS.items()}}

    def create(self, kind, data):
        item = {"name": text_field(data, "name", 100)}
        if kind == "projects": item["guidelines"] = text_field(data, "guidelines", None, False, False)
        if kind == "sessions":
            item.update(project_id=text_field(data, "project_id"), member_id=text_field(data, "member_id"))
        return self.repo.create(kind, item)

    def guidelines(self, data):
        session_id = text_field(data, "session_id", required=False)
        if session_id:
            return self.repo.session(session_id)["guidelines"]
        project_id = text_field(data, "project_id", required=False)
        if not project_id: return ""
        project = next((p for p in self.repo.bootstrap()["projects"] if p["id"] == project_id), None)
        if project is None: raise ValueError("프로젝트를 확인해 주세요.")
        return project["guidelines"]

    def evaluate(self, data):
        p = {"text": text_field(data, "text", None, strip=False), "context": text_field(data, "context", None, False, False),
             "session_id": text_field(data, "session_id", required=False), "request_id": text_field(data, "request_id", 100),
             "task": data.get("task", "auto"), "parent_id": data.get("parent_id") or ""}
        p["title"] = text_field(data, "title", 150, False) or p["text"].strip().splitlines()[0][:70]
        if p["task"] not in ("auto", "simple", "development", "writing", "analysis"):
            raise ValueError("작업 종류를 확인해 주세요.")
        if not isinstance(p["parent_id"], str): raise ValueError("원본 ID를 확인해 주세요.")
        existing = self.repo.by_request(p["request_id"])
        if existing:
            if any(existing[k] != p[k] for k in ("text", "context", "session_id", "title", "task")):
                raise ValueError("동일 요청 ID를 다른 내용에 재사용할 수 없습니다.")
            return self.repo.get(existing["id"])
        guidelines = self.guidelines(data)
        if p["parent_id"] and self.repo.get(p["parent_id"])["session_id"] != p["session_id"]:
            raise ValueError("원본과 같은 세션을 선택하거나 새 프롬프트로 시작해 주세요.")
        context = p["context"] + ("\n프로젝트 규칙:\n" + guidelines if guidelines else "")
        evaluator = self.evaluator(data.get("allow_remote", False))
        result = validate_evaluation(evaluator.evaluate(p["text"], context, p["task"]), p["text"], context)
        result["project_context"] = guidelines
        if not p["session_id"]:
            return {**p, "id": "", "revision": 0, "engine": evaluator.label, "result": result,
                    "score": result["score"], "grade": result["grade"], "stored": False}
        return self.repo.get(self.repo.save(p, result, evaluator.label)["id"])

    def support(self, data):
        prompt_id = text_field(data, "prompt_id", required=False)
        if prompt_id:
            record = self.repo.get(prompt_id)
        else:
            task = data.get("task", "auto")
            if task not in ("auto", "simple", "development", "writing", "analysis"):
                raise ValueError("작업 종류를 확인해 주세요.")
            record = {"text": text_field(data, "text", None, strip=False),
                      "context": text_field(data, "context", None, False, False), "task": task,
                      "result": {"project_context": self.guidelines(data)}}
        evaluator = self.evaluator(data.get("allow_remote", False))
        # Stored records retain their original project rules; new drafts use the current rules.
        snapshot = record["result"].get("project_context", "")
        evaluated_record = {**record, "context": record["context"] + ("\n프로젝트 규칙:\n" + snapshot if snapshot else "")}
        result = validate_support(evaluator.support(evaluated_record))
        result.update(engine=evaluator.label, stored=bool(prompt_id))
        if prompt_id:
            self.repo.save_support(record["id"], evaluator.label, result)
        return result

    def history(self, filters):
        if filters.get("start") and filters.get("end") and filters["start"] > filters["end"]:
            raise ValueError("종료일은 시작일보다 빠를 수 없습니다.")
        rows = self.repo.history(filters)
        grade_counts = dict(Counter(r["grade"] for r in rows))
        def groups(key):
            values = defaultdict(list)
            for r in rows: values[r[key]].append(r)
            ordered = sorted(values.items()) if key == "created_day" else values.items()
            return [{"key": k, "name": v[0].get({"session_id": "session_name", "member_id": "member_name"}.get(key, key), k),
                     "count": len(v), "average": round(sum(x["score"] for x in v) / len(v), 1),
                     **{g: sum(x["grade"] == g for x in v) for g in ("good", "normal", "bad")}} for k, v in ordered]
        return {"rows": rows, "summary": {"count": len(rows), "average": round(sum(r["score"] for r in rows) / len(rows), 1) if rows else None,
                "grades": grade_counts, "engines": sorted({r["engine"] for r in rows}), "rubrics": sorted({r["rubric"] for r in rows})},
                "daily": groups("created_day"), "sessions": groups("session_id"), "members": groups("member_id")}
