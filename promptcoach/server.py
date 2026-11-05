import json
import sqlite3
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from .config import Settings
from .repository import Repository
from .service import CoachService
from .evaluation.contracts import EvaluationError

WEB = Path(__file__).parent / "web"
MAX_BODY = 16 * 1024 * 1024

def create_server(data_dir, port=8765):
    service = CoachService(Repository(Path(data_dir) / "coach.sqlite3"), Settings(data_dir))

    class Handler(BaseHTTPRequestHandler):
        server_version = "PromptCoach/1.0"

        def log_message(self, fmt, *args):
            # Do not log prompt text, API credentials, or query strings.
            pass

        def secure(self, mutation=False):
            port = self.server.server_port
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in allowed:
                raise PermissionError("로컬 주소로 접속해 주세요.")
            if mutation:
                if self.headers.get("X-Prompt-Coach") != "1": raise PermissionError("앱 화면에서 요청해 주세요.")
                origin = self.headers.get("Origin")
                if origin and origin not in {"http://" + h for h in allowed}:
                    raise PermissionError("다른 웹사이트의 요청은 허용하지 않습니다.")
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("JSON 요청이 필요합니다.")

        def send(self, payload, status=200, content_type="application/json; charset=utf-8", filename=None):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if filename: self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def dispatch(self):
            parsed = urlparse(self.path)
            path = parsed.path
            self.secure(self.command == "POST")
            if self.command == "GET":
                filters = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
                if path == "/api/bootstrap": return self.send(service.bootstrap())
                if path == "/api/history": return self.send(service.history(filters))
                if path == "/api/export":
                    return self.send(json.dumps({"schema_version": 1, "timezone": "UTC+09:00", **service.history(filters)}, ensure_ascii=False, indent=2).encode(), filename="prompt-coach-history.json")
                if path == "/api/backup": return self.send(service.repo.backup(), content_type="application/octet-stream", filename="prompt-coach-backup.sqlite3")
                if path in ("/", "/app.js", "/style.css"):
                    file = WEB / ("index.html" if path == "/" else path[1:])
                    content_type = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[file.suffix]
                    return self.send(file.read_bytes(), content_type=content_type + "; charset=utf-8")
                return self.send({"error": "찾을 수 없는 경로입니다."}, 404)
            if self.command == "POST":
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY: raise ValueError("AI 요청 전송 한도(16 MiB)를 초과했습니다. 작성한 내용은 편집기에 유지됩니다. 복사 기능은 계속 사용할 수 있습니다.")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict): raise ValueError("JSON 객체를 보내 주세요.")
                if path in ("/api/projects", "/api/members", "/api/sessions"):
                    return self.send(service.create(path.split("/")[-1], data), 201)
                if path == "/api/evaluate": return self.send(service.evaluate(data))
                if path == "/api/support": return self.send(service.support(data))
                if path == "/api/settings": return self.send(service.settings.update(data))
                return self.send({"error": "찾을 수 없는 경로입니다."}, 404)

        def handle_request(self):
            try:
                self.dispatch()
            except PermissionError as e: self.send({"error": str(e)}, 403)
            except EvaluationError as e: self.send({"error": str(e)}, 502)
            except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as e:
                message = "선택한 프로젝트·작성자·세션을 확인해 주세요." if isinstance(e, (KeyError, TypeError, sqlite3.IntegrityError)) else str(e)
                self.send({"error": message}, 400)
            except ConnectionError: pass
            except Exception:
                self.send({"error": "내부 처리에 실패했습니다. 앱을 다시 시작하고 DB 폴더의 쓰기 권한을 확인해 주세요."}, 500)

        do_GET = handle_request
        do_POST = handle_request

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.service = service
    return server
