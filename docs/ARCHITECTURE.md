# 구조와 확장 지점

UI, HTTP 라우팅, 서비스, 평가 어댑터, 데이터 저장을 분리합니다. 전체 앱은 Python 표준 라이브러리와 브라우저 기본 기능으로 실행됩니다.

```text
run.py                        실행 옵션 및 로컬 서버 시작
promptcoach/
  catalog.py                  17개 기법·평가 항목·가중치·루브릭 버전
  examples.py                 기법별 학습 예시 3개·제목·프롬프트·적용 포인트
  config.py                   공급자/모델 카탈로그·설정 검증·원자적 저장·주소별 메모리 키
  repository.py               SQLite 스키마·트랜잭션·조회·백업
  service.py                  사용 사례·입력 검증·점수 저장·집계
  server.py                   HTTP 라우팅·JSON 오류·로컬 접근 보호
  evaluation/
    contracts.py              JSON Schema·응답 검증·서버 점수 계산
    local.py                  설명 가능한 비AI 규칙 점검
    ai.py                     Ollama / OpenAI 호환 / Claude Messages API 어댑터
  web/
    index.html                한국어 UI와 접근성 레이블
    style.css                 반응형 레이아웃
    app.js                    API 연동·초안·그래프·이력 화면
tests/test_coach.py            단위 및 HTTP 통합 테스트
tests/test_providers.py        키 분리·Claude 전송/응답·서비스 통합 테스트
```

## 평가 데이터 흐름

학습 예시는 bootstrap의 `examples` 필드로만 UI에 전달합니다. 키는 기법 ID이며 값은 title/prompt/explanation을 가진 예시 목록입니다. AI에 전달하는 catalog에는 예시를 포함하지 않아 학습 화면을 열어도 평가 프롬프트 길이나 API 비용이 증가하지 않습니다. UI의 예시 선택·숨김은 브라우저에서 처리합니다.

1. HTTP가 JSON 입력과 로컬 요청 여부를 검증합니다.
2. 서비스가 원본 버전·작업 종류와 선택된 세션/프로젝트를 검증합니다. 프롬프트·문맥의 고정 글자 수 제한은 없습니다.
3. 프로젝트 규칙을 평가 시점의 스냅샷으로 추가합니다.
4. 선택한 어댑터가 6개 항목과 기법 근거를 반환합니다.
5. 공통 계약이 응답을 검증하고 적용 항목으로 총점을 다시 계산합니다.
6. 세션을 선택한 점검만 SQLite 트랜잭션으로 버전을 저장합니다. 세션 없는 점검과 현재 초안 Support는 기록 없이 결과만 반환합니다.

에러 시 성공 점수나 부분 기록을 만들지 않습니다. 요청 ID는 저장 중복을 방지합니다. 같은 요청을 동시에 보내면 AI 호출 자체가 중복될 수 있지만 DB 기록은 한 번만 저장합니다. 향후 작업 큐를 도입하면 평가 작업 테이블에서 호출 단계까지 중복 방지를 확장할 수 있습니다.

## 새 평가 제공자 추가

어댑터는 `label`, `evaluate(text, context, task)`, `support(record)`를 제공하면 됩니다. 데이터 반환 구조는 contracts.py의 스키마를 사용하세요. service.py의 evaluator 팩토리와 config.py의 제공자 검증, 설정 UI에 새 제공자를 등록합니다. 새 제공자도 반드시 공통 응답 검증을 통과해야 합니다.

AI HTTP의 기본 주소에 OpenAI 호환 서버를 연결할 수 있습니다. HTTPS, Chat Completions와 JSON Schema 지원이 필요합니다. 제공자마다 응답 구조가 다르면 별도 어댑터를 추가하세요.

Claude 제공자 ID는 `anthropic`입니다. `/v1/messages`에 별도 system, user messages, max_tokens, output_config.format을 보냅니다. 숫자 범위는 Claude가 스키마에서 지원하지 않으므로 복사본에서 제거하고 공통 검증기로 0~5 범위를 검사합니다. 원본 스키마는 OpenAI/Ollama용으로 보존합니다. 거절·응답 중단은 실패로 처리합니다. `config.py`의 PROVIDERS를 bootstrap에 전달해 UI의 모델 선택 예시와 기본 주소를 공유합니다. 새 외부 공급자는 service.py와 UI의 외부 전송 동의 조건에도 등록하세요.

API 키는 `(provider, base_url)`별로 메모리에 보관하며 설정/DB/응답에 노출하지 않습니다. 공급자별 환경변수는 공식 주소에만 적용합니다. 기존 flat settings.json과 DB 스키마 1을 그대로 읽습니다. 정적 파일 MIME은 Windows 레지스트리 영향으로 JavaScript 실행이 차단되지 않도록 서버에서 명시합니다.

## 평가 기준 변경

`catalog.py`의 DIMENSIONS와 설명·가중치를 수정하고 RUBRIC_VERSION을 증가시키세요. 항목 ID를 추가하면 스키마·규칙 점검·AI 지시·UI 설명·계약 테스트도 함께 갱신해야 합니다. 과거 기록은 재계산하지 않으며 기존 루브릭과 모델 이름을 유지합니다.

등급 경계는 `grade()`에서 관리합니다. 점수는 학습 피드백용이며 사람의 능력 인증이나 성과 예측으로 사용하지 않습니다. 더 신뢰할 수 있는 평가가 필요하면 고정 과제·사람 평가·실제 작업 결과로 루브릭을 보정하고, 사전 점수와 사후 성과를 별도 필드로 기록하세요.

## DB 변경

현재 schema version은 1입니다. `PRAGMA user_version`으로 관리합니다. 미래 스키마를 구버전 앱으로 열면 거절합니다. 새 버전은 Repository 초기화에 순차 마이그레이션과 백업 검증 테스트를 추가하세요. 각 요청은 전용 연결을 사용하며 WAL, foreign_keys, busy_timeout을 적용합니다. 쓰기는 BEGIN IMMEDIATE 트랜잭션으로 버전 번호를 할당합니다.

## 배포 범위와 확장

현재는 한 PC의 소규모 연습용입니다. 전체 필터 결과를 메모리에서 집계하고 브라우저로 반환하므로 이력이 매우 많으면 페이징과 SQL 집계가 필요합니다. 장시간 AI 평가는 HTTP 요청 안에서 동기 처리합니다. 팀 중앙 서버로 확장할 때는 인증·사용자별 권한, 작업 큐, 비동기 API, 페이지 조회, 중앙 DB와 비밀 관리가 우선입니다. 모델별 처리량과 비용 제한도 별도로 설계해야 합니다.

현재는 실제 대상 프롬프트를 실행하지 않으며, 외부 에디터나 Codex 대화도 자동 수집하지 않습니다. 사용자가 명시적으로 입력한 텍스트를 평가합니다.

## 작성 중심 흐름

편집·자동 저장·복사는 브라우저에서 처리합니다. Support는 평가를 선행하지 않고 별도의 확인 항목 지시와 CLARIFICATION_SCHEMA로 한 번 요청합니다. AI는 topic/reason/question을 반환하며 어댑터는 원문을 그대로 보존하고 최대 두 개의 확인 빈칸을 덧붙입니다. 외부 API 응답은 기존 improved_prompt/changes/questions 형식을 유지하고 SUPPORT_SCHEMA에 대응하는 검증을 통과합니다. Qwen3 요청은 think=false를 사용합니다. AI 요청 중에는 해당 요청 버튼만 잠그며 작성·복사·화면 이동은 유지합니다. 요청 시 초안 스냅샷과 편집 세대를 비교해 이전 결과가 새 초안을 덮어쓰지 않도록 합니다. AbortController는 브라우저 대기를 취소하며 서버 추론 중단은 보장하지 않습니다.

평가의 evidence는 정확 일치 여부를 evidence_verified로 기록합니다. 불일치는 AI의 해석으로 구분해 표시하며 다시 요청하거나 작업을 막지 않습니다. 필수 점수 형식 등 응답 계약 검증은 유지합니다. DB 스키마 변경 없이 기존 이력을 읽습니다.
