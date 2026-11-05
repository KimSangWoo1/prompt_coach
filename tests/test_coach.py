import copy
from contextlib import closing
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from promptcoach.catalog import grade, DIMENSIONS
from promptcoach.config import Settings
from promptcoach.evaluation.contracts import validate_evaluation, validate_support, EvaluationError
from promptcoach.evaluation.local import LocalEvaluator
from promptcoach.evaluation.ai import AIEvaluator
from promptcoach.repository import Repository, KST
from promptcoach.server import create_server
from promptcoach.service import CoachService

TEXT = "Unity 환경에서 UI 로딩 취소를 구현해줘. 공개 API는 유지하고 결과를 표로 작성해줘. 씬 종료 후 중복 생성 여부를 테스트하고 검증 결과를 보고해줘."

class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.repo = Repository(self.directory / 'coach.sqlite3')
        self.settings = Settings(self.directory)
        self.service = CoachService(self.repo, self.settings)
        boot = self.repo.bootstrap()
        self.project, self.member = boot['projects'][0], boot['members'][0]
        self.session = self.service.create('sessions', {'name': '첫 연습', 'project_id': self.project['id'], 'member_id': self.member['id']})
    def tearDown(self): self.temp.cleanup()
    def payload(self, **extra):
        return {'text': TEXT, 'context': '', 'task': 'development', 'session_id': self.session['id'], 'request_id': 'request-1', **extra}
    def evaluate(self, **extra): return self.service.evaluate(self.payload(**extra))

class RubricTests(unittest.TestCase):
    def test_grade_thresholds(self):
        self.assertEqual([grade(x) for x in [0, 54.9, 55, 79.9, 80, 100]], ['bad', 'bad', 'normal', 'normal', 'good', 'good'])
    def test_score_recomputed_not_model_total(self):
        raw = LocalEvaluator().evaluate(TEXT, '', 'development'); raw['score'] = 100000
        r = validate_evaluation(raw, TEXT)
        self.assertLessEqual(r['score'], 100)
        self.assertNotEqual(r['score'], raw['score'])
    def test_simple_short_request_excludes_unnecessary_dimensions(self):
        text = '“안녕하세요”를 자연스러운 영어 한 문장으로 번역해줘.'
        r = validate_evaluation(LocalEvaluator().evaluate(text, '', 'simple'), text)
        self.assertEqual(r['grade'], 'good')
        self.assertTrue(all(not d['applicable'] for d in r['dimensions'] if d['id'] in ('context','constraints','verification','examples')))
    def test_vague_request_is_bad(self):
        text = '만들어줘'
        r = validate_evaluation(LocalEvaluator().evaluate(text, '', 'development'), text)
        self.assertEqual(r['grade'], 'bad')
    def test_missing_dimensions_rejected(self):
        raw = LocalEvaluator().evaluate(TEXT, '', 'development');raw['dimensions'].pop()
        with self.assertRaises(EvaluationError): validate_evaluation(raw, TEXT)
    def test_duplicate_dimensions_rejected(self):
        raw = LocalEvaluator().evaluate(TEXT, '', 'development');raw['dimensions'][1] = raw['dimensions'][0]
        with self.assertRaises(EvaluationError): validate_evaluation(raw, TEXT)
    def test_paraphrased_evidence_is_marked_as_interpretation(self):
        raw = LocalEvaluator().evaluate(TEXT, '', 'development');raw['dimensions'][0]['evidence']='원문에 없는 문장'
        result = validate_evaluation(raw, TEXT)
        self.assertFalse(result['dimensions'][0]['evidence_verified'])
        self.assertEqual(result['dimensions'][0]['evidence'], '원문에 없는 문장')
    def test_noninteger_and_out_of_range_rejected(self):
        for value in [True, 4.5, -1, 6, '5']:
            raw=LocalEvaluator().evaluate(TEXT, '', 'development');raw['dimensions'][0]['score']=value
            with self.subTest(value=value), self.assertRaises(EvaluationError):validate_evaluation(raw,TEXT)
    def test_unknown_technique_rejected(self):
        raw=LocalEvaluator().evaluate(TEXT,'','development');raw['techniques'][0]['id']='magic'
        with self.assertRaises(EvaluationError):validate_evaluation(raw,TEXT)
    def test_clarity_cannot_be_excluded(self):
        raw=LocalEvaluator().evaluate(TEXT,'','development');raw['dimensions'][0]['applicable']=False
        with self.assertRaises(EvaluationError):validate_evaluation(raw,TEXT)
    def test_unfilled_support_not_rewarded(self):
        text=TEXT+'\n검증 기준\n[직접 입력: 성공 조건을 입력하세요]'
        r=validate_evaluation(LocalEvaluator().evaluate(text,'','development'),text)
        self.assertLess(r['score'],55)
    def test_invalid_support_rejected(self):
        with self.assertRaises(EvaluationError): validate_support({'improved_prompt':'','changes':[],'questions':[]})

class PersistenceTests(Fixture):
    def test_save_and_reopen(self):
        record=self.evaluate();reopened=Repository(self.repo.path)
        self.assertEqual(reopened.get(record['id'])['text'],TEXT)
        self.assertEqual(record['result']['rubric'],'readiness-1.0')
    def test_duplicate_request_is_idempotent(self):
        a=self.evaluate();b=self.evaluate();self.assertEqual(a['id'],b['id'])
        self.assertEqual(len(self.repo.history({'latest':'0'})),1)
    def test_duplicate_request_different_payload_rejected(self):
        self.evaluate()
        with self.assertRaises(ValueError):self.evaluate(text='새 내용')
    def test_revisions_preserve_original(self):
        a=self.evaluate();b=self.evaluate(request_id='r2',parent_id=a['id'],text=TEXT+' 기존 동작을 유지해줘.')
        self.assertEqual(a['family_id'],b['family_id']);self.assertEqual(b['revision'],2)
        self.assertEqual(self.repo.get(a['id'])['text'],TEXT)
        self.assertEqual(len(self.repo.history({})),1)
        self.assertEqual(len(self.repo.history({'latest':'0'})),2)
    def test_cross_session_parent_rejected(self):
        a=self.evaluate();other=self.service.create('sessions',{'name':'다른 세션','project_id':self.project['id'],'member_id':self.member['id']})
        with self.assertRaises(ValueError): self.evaluate(request_id='r2',parent_id=a['id'],session_id=other['id'])
    def test_support_keeps_original_grade(self):
        a=self.evaluate();support=self.service.support({'prompt_id':a['id']})
        self.assertIn('improved_prompt',support)
        self.assertEqual(self.repo.get(a['id'])['result'],a['result'])
        with self.repo.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM supports').fetchone()[0],1)
    def test_team_project_filters(self):
        self.evaluate()
        project=self.service.create('projects',{'name':'팀 프로젝트','guidelines':'Python 3.11 환경 사용'})
        member=self.service.create('members',{'name':'동료'})
        session=self.service.create('sessions',{'name':'팀 연습','project_id':project['id'],'member_id':member['id']})
        self.evaluate(request_id='r2',session_id=session['id'])
        filtered=self.service.history({'project_id':project['id'],'member_id':member['id']})
        self.assertEqual(filtered['summary']['count'],1);self.assertEqual(filtered['members'][0]['name'],'동료')
    def test_project_guideline_snapshot(self):
        with self.repo.connect() as c:c.execute('UPDATE projects SET guidelines=?',('IL2CPP 환경 사용',))
        a=self.evaluate()
        with self.repo.connect() as c:c.execute('UPDATE projects SET guidelines=?',('바뀐 규칙',))
        self.assertEqual(self.repo.get(a['id'])['result']['project_context'],'IL2CPP 환경 사용')
    def test_date_filters_latest_within_period(self):
        a=self.evaluate();b=self.evaluate(request_id='r2',parent_id=a['id'])
        with self.repo.connect() as c:
            c.execute('UPDATE prompts SET created_day=? WHERE id=?',('2026-01-01',a['id']))
            c.execute('UPDATE prompts SET created_day=? WHERE id=?',('2026-01-02',b['id']))
        rows=self.service.history({'start':'2026-01-01','end':'2026-01-01'})['rows']
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['id'],a['id'])
        self.assertEqual(len(self.service.history({'start':'2026-01-03'})['rows']),0)
    def test_latest_records_stay_chronological(self):
        a=self.evaluate();b=self.evaluate(request_id='r2')
        a2=self.evaluate(request_id='r3',parent_id=a['id'])
        self.assertEqual([r['id'] for r in self.repo.history({})],[b['id'],a2['id']])
    def test_reversed_dates_rejected(self):
        with self.assertRaises(ValueError):self.service.history({'start':'2026-01-02','end':'2026-01-01'})
    def test_empty_dashboard(self):
        d=self.service.history({});self.assertEqual(d['summary']['count'],0);self.assertIsNone(d['summary']['average'])
    def test_backup_contains_committed_wal(self):
        self.evaluate();path=self.directory/'backup.sqlite3';path.write_bytes(self.repo.backup())
        with closing(sqlite3.connect(path)) as c:self.assertEqual(c.execute('SELECT count(*) FROM prompts').fetchone()[0],1)
    def test_newer_database_refused(self):
        with self.repo.connect() as c:c.execute('PRAGMA user_version=99')
        with self.assertRaises(ValueError):Repository(self.repo.path)
    def test_input_bounds_and_invalid_session(self):
        for change in [{'text':' '},{'session_id':'unknown'},{'task':'invalid'}]:
            with self.subTest(change=list(change)),self.assertRaises(ValueError):self.evaluate(**change)
    def test_sql_injection_in_filter_is_literal(self):
        self.evaluate();self.assertEqual(len(self.repo.history({'project_id':"' OR 1=1 --"})),0)
    def test_settings_key_is_not_persisted(self):
        self.settings.update({'api_key':'test-only-never-real','provider':'openai','base_url':'https://api.openai.com/v1','model':'example'})
        self.assertNotIn('test-only',self.settings.path.read_text())
        self.assertNotIn('api_key',self.settings.public())
    def test_remote_requires_consent(self):
        self.settings.update({'provider':'openai','base_url':'https://api.openai.com/v1'})
        with self.assertRaises(ValueError):self.evaluate()
        self.assertEqual(self.repo.history({}),[])
    def test_ai_failure_does_not_write_or_silently_fallback(self):
        self.settings.update({'provider':'ollama'})
        with patch.object(AIEvaluator,'evaluate',side_effect=EvaluationError('server unavailable')):
            with self.assertRaises(EvaluationError):self.evaluate()
        self.assertEqual(self.repo.history({}),[])
    def test_ai_response_contract_is_applied(self):
        self.settings.update({'provider':'ollama'})
        raw=LocalEvaluator().evaluate(TEXT,'','development');raw['score']=9999
        with patch.object(AIEvaluator,'evaluate',return_value=raw):r=self.evaluate()
        self.assertTrue(r['engine'].startswith('ollama:'));self.assertLessEqual(r['score'],100)
    def test_public_settings_validations(self):
        for changes in [{'provider':'ollama','base_url':'http://external.test:11434'},{'provider':'openai','base_url':'http://api.test/v1'},{'timeout':-1}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.settings.update(changes)

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.server=create_server(self.temp.name,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def request(self,path,data=None,headers=None):
        req=Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','X-Prompt-Coach':'1',**(headers or {})})
        return urlopen(req,timeout=3)
    def test_static_and_bootstrap(self):
        with self.request('/') as r:self.assertIn(b'Prompt Coach',r.read());self.assertIn("script-src 'self'",r.headers['Content-Security-Policy'])
        with self.request('/api/bootstrap') as r:self.assertIn('projects',json.load(r))
    def test_static_asset_types_do_not_depend_on_windows_registry(self):
        for path, mime in [('/app.js', 'text/javascript'), ('/style.css', 'text/css'), ('/', 'text/html')]:
            with self.subTest(path=path), self.request(path) as response:
                self.assertEqual(response.headers.get_content_type(), mime)
    def test_full_evaluation_export_flow(self):
        with self.request('/api/bootstrap') as r:boot=json.load(r)
        with self.request('/api/sessions',{'name':'HTTP 테스트','project_id':boot['projects'][0]['id'],'member_id':boot['members'][0]['id']}) as r:s=json.load(r)
        with self.request('/api/evaluate',{'text':TEXT,'session_id':s['id'],'request_id':'http-1'}) as r:record=json.load(r)
        with self.request('/api/support',{'prompt_id':record['id']}) as r:self.assertIn('improved_prompt',json.load(r))
        with self.request('/api/export') as r:self.assertEqual(json.load(r)['summary']['count'],1)
        with self.request('/api/backup') as r:self.assertTrue(r.read().startswith(b'SQLite format 3'))
    def test_cross_origin_mutation_denied(self):
        with self.assertRaises(HTTPError) as ctx:self.request('/api/members',{'name':'x'},{'Origin':'https://evil.test'})
        self.assertEqual(ctx.exception.code,403)

    def test_host_rebinding_denied(self):
        with self.assertRaises(HTTPError) as ctx:self.request('/api/bootstrap',headers={'Host':'evil.test'})
        self.assertEqual(ctx.exception.code,403)
    def test_missing_mutation_header_denied(self):
        req=Request(self.base+'/api/members',data=b'{"name":"x"}',headers={'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as ctx:urlopen(req)
        self.assertEqual(ctx.exception.code,403)


class AITransportTests(unittest.TestCase):
    def test_ollama_wire_protocol_with_local_fake_server(self):
        seen=[]
        class Fake(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));seen.append((self.path,data))
                request=json.loads(data['messages'][1]['content'])
                result=LocalEvaluator().evaluate(request['prompt'],request['context'],request['task'])
                content=json.dumps({'message':{'content':json.dumps(result,ensure_ascii=False)}}).encode()
                self.send_response(200);self.end_headers();self.wfile.write(content)
        server=ThreadingHTTPServer(('127.0.0.1',0),Fake);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            adapter=AIEvaluator({'provider':'ollama','base_url':f'http://127.0.0.1:{server.server_port}','model':'fake-transport-test','timeout':10},'')
            raw=adapter.evaluate(TEXT,'','development');result=validate_evaluation(raw,TEXT)
            self.assertLessEqual(result['score'],100);self.assertEqual(seen[0][0],'/api/chat')
            self.assertFalse(seen[0][1]['stream']);self.assertIn('properties',seen[0][1]['format'])
        finally:server.shutdown();server.server_close();thread.join()
    def test_openai_wire_contract_without_external_call(self):
        raw=LocalEvaluator().evaluate(TEXT,'','development')
        data=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(raw)}}]}).encode()
        response=io.BytesIO(data)
        adapter=AIEvaluator({'provider':'openai','base_url':'https://example.invalid/v1','model':'fake-test','timeout':10},'test-key')
        with patch('promptcoach.evaluation.ai.urlopen',return_value=response) as call:
            validate_evaluation(adapter.evaluate(TEXT,'','development'),TEXT)
        req=call.call_args.args[0];body=json.loads(req.data)
        self.assertEqual(req.full_url,'https://example.invalid/v1/chat/completions')
        self.assertEqual(req.get_header('Authorization'),'Bearer test-key')
        self.assertTrue(body['response_format']['json_schema']['strict'])
    def test_refusal_and_truncation_rejected(self):
        adapter=AIEvaluator({'provider':'openai','base_url':'https://example.invalid/v1','model':'fake-test','timeout':10},'test-key')
        for reason,message in [('length',{'content':'{}'}),('stop',{'refusal':'declined','content':None})]:
            data=json.dumps({'choices':[{'finish_reason':reason,'message':message}]}).encode()
            with patch('promptcoach.evaluation.ai.urlopen',return_value=io.BytesIO(data)),self.assertRaises(EvaluationError):adapter.evaluate(TEXT,'','auto')

if __name__=='__main__':unittest.main()
