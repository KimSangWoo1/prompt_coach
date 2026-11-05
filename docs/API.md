# 로컬 API

서버 기본 주소는 `http://127.0.0.1:8765`입니다. 외부 배포용 API가 아닙니다.

POST는 `Content-Type: application/json`, `X-Prompt-Coach: 1` 헤더가 필요합니다. Host는 해당 포트의 localhost/127.0.0.1이어야 하며, Origin이 있으면 같은 로컬 origin이어야 합니다. 서버는 CORS 허용 헤더를 보내지 않습니다. 이 검사는 외부 웹페이지의 임의 요청을 제한하기 위한 것으로 사용자 인증을 대신하지 않습니다.

| 메서드 | 경로 | 역할 |
| --- | --- | --- |
| GET | /api/bootstrap | 프로젝트·작성자·세션·공개 설정·기법·학습 예시·루브릭 |
| POST | /api/projects | name, guidelines로 프로젝트 추가 |
| POST | /api/members | name으로 작성자 추가 |
| POST | /api/sessions | name, project_id, member_id로 세션 추가 |
| POST | /api/evaluate | 선택 점검, 세션이 있으면 이력 저장 |
| POST | /api/support | 현재 초안 또는 저장된 prompt_id에서 개선안 생성 |
| POST | /api/settings | 제공자·모델·주소·타임아웃·메모리 키 설정 |
| GET | /api/history | 필터 결과, 요약, 날짜/세션/작성자 집계 |
| GET | /api/export | 같은 필터를 적용한 JSON 다운로드 |
| GET | /api/backup | SQLite backup API로 일관된 DB 다운로드 |

## 평가 요청

```json
{
  "session_id": "bootstrap 또는 생성 응답의 실제 ID",
  "request_id": "새 UUID 등 재시도 간 유지할 ID",
  "title": "UI 로딩 취소",
  "text": "평가할 프롬프트",
  "context": "추가 배경 자료",
  "task": "development",
  "parent_id": "이전 버전 ID 또는 빈 문자열",
  "allow_remote": false
}
```

task는 auto/simple/development/writing/analysis 중 하나입니다. text/context에는 별도 글자 수 제한을 두지 않으며 앞뒤 공백도 보존합니다. 전체 JSON 요청은 메모리 보호를 위해 16 MiB까지 받습니다. title은 최대 150자입니다. session_id가 없으면 점검만 반환하고 stored=false 및 빈 id로 응답합니다. project_id로 프로젝트 규칙을 선택할 수 있습니다. parent_id는 같은 세션의 저장 기록이어야 합니다. 응답에는 생성된 id, family_id, revision, 원문, 배경, 시각, 평가 방식, 점수, 등급, 전체 result가 들어 있습니다.

외부 AI 사용 시 allow_remote=true가 필요합니다. Support는 text/context/task/project_id/session_id(선택)/allow_remote로 현재 초안을 받을 수 있습니다. 평가·세션 없이 호출할 수 있으며 AI 개선 요청은 한 번만 실행하고 stored=false를 반환합니다. 기존 prompt_id 요청은 계속 지원하며 그 경우 원본 기록에 개선안을 저장합니다. 평가와 개선의 실행 제공자는 현재 설정을 따르며 각각 실제 사용한 engine을 기록합니다. 과거 기록은 당시 사용한 프로젝트 규칙 스냅샷을 보존합니다.

## 이력 필터

project_id / member_id / session_id / engine / rubric / start / end / latest를 지원합니다. 날짜는 YYYY-MM-DD입니다. latest=1은 필터 범위 안의 최신 버전, latest=0은 모든 버전입니다. 점수·버전 전체를 포함한 분석 결과를 반환하므로 개인 원문이 포함됩니다. 외부에 내보낼 때 공유 범위를 직접 확인하세요.

## 오류

- 400: 잘못된 입력, 알 수 없는 세션, 다른 세션의 원본, 설정 형식 오류
- 403: 잘못된 Host/Origin/요청 헤더
- 404: 없는 경로
- 502: AI 연결·시간 초과·응답 계약 검증 오류
- 500: 내부 저장·처리 오류

응답은 `{ "error": "사용자에게 표시할 설명" }` 형태입니다. API 키나 외부 API의 원문 오류 응답은 반환하지 않습니다.

## 공급자와 모델 설정

`GET /api/bootstrap`의 `providers`는 공급자 ID별 name, model, base_url, models(드롭다운 목록)를 반환합니다. UI에서는 공급자에 맞는 드롭다운으로 모델을 선택합니다. 목록은 계정별 이용 권한이나 연결 성공을 보장하지 않습니다.

`examples`는 기법 ID별 title/prompt/explanation 예시 목록입니다. 현재 17개 기법마다 3개씩 제공합니다. UI에서 예시를 선택해도 별도 API 요청이나 AI 평가를 실행하지 않습니다.

```json
{
  "provider": "anthropic",
  "model": "claude-sonnet-5-5",
  "base_url": "https://api.anthropic.com/v1",
  "timeout": 120,
  "api_key": "사용자가 발급한 Claude API 키",
  "clear_key": false
}
```

`POST /api/settings`에 보냅니다. provider는 local/ollama/openai/anthropic입니다. 공급자를 바꿀 때 model/base_url을 생략하면 해당 공급자의 기본값을 사용합니다. 응답은 공개 설정과 `api_key_configured`이며 키 값은 반환하지 않습니다. 키는 공급자·주소별 메모리에서만 관리합니다. 비어 있는 api_key는 그 주소의 기존 키를 유지하고, clear_key=true는 그 주소의 키만 지웁니다. OpenAI와 Claude 모두 평가/Support 요청에서 allow_remote=true가 필요합니다.

인용 근거에는 evidence_verified가 추가됩니다. true이면 원문/문맥의 실제 인용, false이면 AI의 해석입니다. false인 근거도 점검 전체를 실패시키지 않습니다.

AI Support는 내부적으로 핵심 확인 항목(topic/reason/question)을 요청하고, 서버가 원문에 확인 빈칸을 덧붙여 기존 improved_prompt/changes/questions 응답으로 변환합니다. 원문·조건·앞뒤 공백은 보존하고 확인 항목은 최대 2개입니다. 공개 요청/응답 형식과 DB 스키마는 변경하지 않습니다.
