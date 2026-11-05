import json
import os
import threading
from pathlib import Path
from urllib.parse import urlparse

DEFAULTS = {"provider": "local", "model": "rules-1.0", "base_url": "http://127.0.0.1:11434", "timeout": 120}
PROVIDERS = {
    "local": {"name": "규칙 기반 점검", "model": "rules-1.0", "base_url": "http://127.0.0.1:11434", "models": []},
    "ollama": {"name": "Ollama", "model": "qwen3:8b-q4_K_M", "base_url": "http://127.0.0.1:11434", "models": ["qwen3:8b-q4_K_M", "qwen2.5:3b", "qwen2.5:7b", "qwen2.5:14b", "qwen2.5:32b"]},
    "openai": {"name": "OpenAI", "model": "gpt-4.1-mini", "base_url": "https://api.openai.com/v1", "models": ["gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "gpt-4.1-mini", "gpt-4.1"]},
    "anthropic": {"name": "Claude", "model": "claude-sonnet-5-5", "base_url": "https://api.anthropic.com/v1", "models": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"]},
}

class Settings:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "settings.json"
        self.lock = threading.Lock()
        self.keys = {}
        self.values = dict(DEFAULTS)
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.values.update({k: saved[k] for k in DEFAULTS if k in saved})
            self.validate(self.values)
        for provider, variable in (("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")):
            self.keys[(provider, PROVIDERS[provider]["base_url"])] = os.environ.get(variable, "").strip()
        if self.values["provider"] in ("openai", "anthropic") and os.environ.get("PROMPTCOACH_API_KEY"):
            self.keys[self.key_scope(self.values)] = os.environ["PROMPTCOACH_API_KEY"].strip()

    @staticmethod
    def key_scope(values):
        # Bind credentials to both provider and destination; switching must not leak another API's key.
        return values["provider"], values["base_url"].rstrip("/")

    @staticmethod
    def validate(v):
        if v["provider"] not in PROVIDERS:
            raise ValueError("지원하지 않는 평가 방식입니다.")
        if type(v["timeout"]) is not int or not 10 <= v["timeout"] <= 300:
            raise ValueError("대기 시간은 10~300초 사이여야 합니다.")
        if not isinstance(v["model"], str) or not v["model"].strip() or len(v["model"]) > 150:
            raise ValueError("모델 이름을 입력해 주세요.")
        if not isinstance(v["base_url"], str):
            raise ValueError("API 주소를 확인해 주세요.")
        u = urlparse(v["base_url"])
        if u.username or u.password or u.query or u.fragment:
            raise ValueError("주소에 인증 정보나 쿼리를 넣을 수 없습니다.")
        if v["provider"] == "ollama" and (u.scheme != "http" or u.hostname not in ("localhost", "127.0.0.1", "::1") or u.path not in ("", "/")):
            raise ValueError("Ollama는 로컬 HTTP 주소만 지원합니다. 예: http://127.0.0.1:11434")
        if v["provider"] in ("openai", "anthropic") and (u.scheme != "https" or not u.hostname):
            raise ValueError("외부 API는 HTTPS 주소를 사용해야 합니다. 예: https://api.openai.com/v1")

    def snapshot(self):
        with self.lock:
            return dict(self.values), self.keys.get(self.key_scope(self.values), "")

    def public(self):
        values, key = self.snapshot()
        return {**values, "api_key_configured": bool(key)}

    def update(self, changes):
        with self.lock:
            values = {**self.values, **{k: changes[k] for k in DEFAULTS if k in changes}}
            if values["provider"] != self.values["provider"] and values["provider"] in PROVIDERS:
                for name in ("model", "base_url"):
                    if name not in changes:
                        values[name] = PROVIDERS[values["provider"]][name]
            self.validate(values)
            values["model"] = values["model"].strip()
            values["base_url"] = values["base_url"].rstrip("/")
            key = changes.get("api_key", "")
            if not isinstance(key, str) or len(key) > 1000:
                raise ValueError("API 키 형식을 확인해 주세요.")
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)
            self.values = values
            if changes.get("clear_key"):
                self.keys[self.key_scope(values)] = ""
            elif key.strip():
                self.keys[self.key_scope(values)] = key.strip()
        return self.public()
