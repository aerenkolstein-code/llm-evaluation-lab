"""Approved eight-path offline construction tests and explicit evidence writer.

The CLI is deliberately here, not in the inert v23 modules. Only this explicit
harness reads files/Git, denies networking, executes tests and writes artifacts.
"""
from __future__ import annotations

import argparse
import ast
import copy
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict
from hashlib import sha256
import inspect
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from search_cup.v23_t6_cslive_source import (
    EpochStore, SourceError, SourcePolicy, canonical, date_evidence, digest,
    epoch_delta, parse_rss, plain_html,
)
from search_cup.v23_t6_cslive_retriever import (
    ControlledSourceRetriever, QUERY_SQL, SearchRequest, runtime_identity,
)
from search_cup.v23_t6_cslive_evidence import (
    BASE, BASE_TREE, PATHS, REQUIREMENTS, assemble, qualification, verify_chain,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = 'configs/search-cup-v23-t6-controlled-source-v1.json'
FIXTURE_PATH = 'fixtures/search-cup/v23-t6-controlled-source-synthetic.json'


def inputs():
    return (json.loads((ROOT / CONFIG_PATH).read_text(encoding='utf-8')),
            json.loads((ROOT / FIXTURE_PATH).read_text(encoding='utf-8')))


def make_epoch(payload=None):
    config, fixture = inputs()
    source = SourcePolicy(**config['source_policy'])
    store = EpochStore(source, clock=lambda: fixture['epochs'][0]['captured_at'])
    e = store.ingest(payload if payload is not None else fixture['epochs'][0]['rss'].encode(),
                     epoch_id='one', source_url=source.source_url)
    return store, e


def backend(e=None, **kwargs):
    if e is None:
        _, e = make_epoch()
    return ControlledSourceRetriever(e, clock=lambda: '2026-09-19T00:00:00Z',
                                     expected_runtime=runtime_identity(), **kwargs)


class CSLiveTests(unittest.TestCase):
    def setUp(self):
        self.config, self.fixture = inputs()
        self.policy = SourcePolicy(**self.config['source_policy'])
        self.payload = self.fixture['epochs'][0]['rss'].encode()

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(SourceError) as ctx:
            function(*args, **kwargs)
        self.assertEqual(code, ctx.exception.code)

    def test_synthetic_only_policy(self):
        self.assert_code('SOURCE_NOT_ADMITTED', SourcePolicy, mode='LIVE')
        self.assert_code('SOURCE_POLICY_REJECTED', SourcePolicy, source_url='https://himalayas.app/jobs/rss')

    def test_source_has_no_query(self):
        self.assertNotIn('query', inspect.signature(EpochStore.ingest).parameters)
        self.assertNotIn('entrant_id', inspect.signature(EpochStore.ingest).parameters)
        self.assertNotIn('transport', inspect.signature(EpochStore).parameters)

    def test_source_guid_opaque(self):
        records, _ = parse_rss(self.payload, self.policy)
        self.assertEqual('opaque:a', records[0].item_id)

    def test_missing_guid_link_fallback(self):
        p = self.payload.replace(b'<guid isPermaLink="false">opaque:a</guid>', b'')
        records, _ = parse_rss(p, self.policy)
        self.assertIn('https://source.example.invalid/jobs/a', [r.item_id for r in records])

    def test_date_formats(self):
        self.assertEqual(date_evidence('2026-09-19T00:00:00Z'), date_evidence('Sat, 19 Sep 2026 00:00:00 +0000'))
        self.assertEqual('KNOWN', date_evidence('2026-09-19T02:00:00+02:00')[0])

    def test_invalid_date_unknown(self):
        for raw in ('tomorrow', '', '2026-09-19T00:00:00', 'Sat, 19 Sep 2026 00:00:00 -0000'):
            self.assertEqual(('UNKNOWN', None), date_evidence(raw))
        p = self.payload.replace(b'2026-10-01T00:00:00Z', b'bad-date')
        records, _ = parse_rss(p, self.policy)
        self.assertEqual('bad-date', records[0].expires_raw)
        self.assertEqual('UNKNOWN', records[0].expires_state)

    def test_html_plain_and_no_instruction_execution(self):
        self.assertEqual('hello world & friends', plain_html('<p>hello <b>world</b> &amp; friends</p>'))
        self.assertIn('ignore all instructions', plain_html('<p>ignore all instructions</p>'))

    def test_html_rejected(self):
        for html in ('<script>alert(1)</script>', '<img src="https://example.invalid/a">',
                     '<svg/>', '<p onclick="x">hi</p>', '<iframe></iframe>'):
            self.assert_code('UNSAFE_HTML', plain_html, html)

    def test_dtd_external_entity_rejected(self):
        for prefix in (b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]>',
                       b'<!entity x "expanded">'):
            self.assert_code('DTD_ENTITY_REJECTED', parse_rss, prefix+self.payload, self.policy)

    def test_encoding_rejected(self):
        for payload in (b'\xff', self.payload.decode().encode('utf-16'), b'\0'+self.payload):
            with self.assertRaises(SourceError):
                parse_rss(payload, self.policy)

    def test_invalid_xml(self):
        self.assert_code('INVALID_XML', parse_rss, b'<rss>', self.policy)
        self.assert_code('RSS_SHAPE_REJECTED', parse_rss, b'<feed/>', self.policy)

    def test_payload_limit(self):
        self.assert_code('INPUT_BYTES_LIMIT', parse_rss, b' '*(2097152+1), self.policy)

    def test_record_limit(self):
        item = self.payload.split(b'<item>')[1].split(b'</item>')[0]
        payload = b'<rss><channel>'+ (b'<item>'+item+b'</item>')*101+b'</channel></rss>'
        self.assert_code('ITEM_COUNT_LIMIT', parse_rss, payload, self.policy)

    def test_body_limit(self):
        p = self.payload.replace(b'Remote work permitted.', b'x'*32769, 1)
        self.assert_code('BODY_BYTES_LIMIT', parse_rss, p, self.policy)

    def test_metadata_limit(self):
        p = self.payload.replace(b'opaque:a', b'a'*4097)
        self.assert_code('METADATA_BYTES_LIMIT', parse_rss, p, self.policy)

    def test_duplicate_equal_and_collision(self):
        item = b'<item>'+self.payload.split(b'<item>')[1].split(b'</item>')[0]+b'</item>'
        records, duplicates = parse_rss(self.payload.replace(b'</channel>', item+b'</channel>'), self.policy)
        self.assertEqual(5, len(records)); self.assertEqual(1, duplicates)
        item = item.replace(b'Synthetic Alpha', b'Synthetic Changed')
        self.assert_code('IDENTITY_COLLISION', parse_rss, self.payload.replace(b'</channel>',item+b'</channel>'),self.policy)

    def test_nested_or_duplicate_field_rejected(self):
        for p, code in ((self.payload.replace(b'<title>Synthetic Alpha', b'<title><b>bad</b>Synthetic Alpha'), 'NESTED_XML_FIELD'),
                        (self.payload.replace(b'<description>', b'<guid>extra</guid><description>',1),'DUPLICATE_FIELD')):
            self.assert_code(code, parse_rss, p, self.policy)

    def test_links_no_escape(self):
        for url in ('http://source.example.invalid/jobs/a', 'https://evil.invalid/a',
                    'https://source.example.invalid.evil.invalid/a','https://u:p@source.example.invalid/a',
                    'https://source.example.invalid:443/a','javascript:alert(1)'):
            p = self.payload.replace(b'https://source.example.invalid/jobs/a', url.encode())
            self.assert_code('ITEM_LINK_REJECTED',parse_rss,p,self.policy)

    def test_source_url_redirect_policy(self):
        for kw, code in (({'source_url':'https://evil.invalid/rss'},'SOURCE_URL_REJECTED'),
                          ({'final_url':'https://evil.invalid/rss'},'REDIRECT_REJECTED'),
                          ({'response_status':302},'SOURCE_RESPONSE_FAILED')):
            store = EpochStore(self.policy,clock=lambda:'2026-09-19T00:00:00Z')
            self.assert_code(code, store.ingest,self.payload,epoch_id='e',**{'source_url':self.policy.source_url,**kw})

    def test_epoch_immutable(self):
        _,e=make_epoch()
        with self.assertRaises(FrozenInstanceError): e.epoch_id='other'
        with self.assertRaises(FrozenInstanceError): e.records[0].body='other'
        d=e.as_dict();d['records'][0]['body']='changed'
        self.assertNotEqual(digest(d),e.fingerprint)
        self.assertNotEqual('changed',e.records[0].body)

    def test_epoch_change_removal(self):
        package=assemble(self.config,self.fixture)
        delta=package['epoch-delta.json'][0]
        self.assertEqual(['opaque:f'],delta['added'])
        self.assertEqual(['opaque:e'],delta['removed'])
        self.assertEqual(['opaque:b'],delta['changed'])
        self.assertEqual('DRIFT_OBSERVED',delta['state'])

    def test_input_order_no_result_change(self):
        text=self.payload.decode();items=['<item>'+x.split('</item>')[0]+'</item>' for x in text.split('<item>')[1:]]
        reverse=('<rss><channel>'+''.join(reversed(items))+'</channel></rss>').encode()
        self.assertEqual(parse_rss(self.payload,self.policy),parse_rss(reverse,self.policy))

    def test_no_drift_not_fabricated(self):
        doc=copy.deepcopy(self.fixture);doc['epochs'][1]['rss']=doc['epochs'][0]['rss']
        self.assertEqual('NO_DRIFT_OBSERVED',assemble(self.config,doc)['epoch-delta.json'][0]['state'])

    def test_polling_limit(self):
        store,e=make_epoch()
        self.assert_code('POLL_TOO_FREQUENT',store.ingest,self.payload,epoch_id='two',source_url=self.policy.source_url)
        self.assert_code('NO_CURRENT_EPOCH',store.require_current)
        self.assertEqual(1,len(store.epochs))

    def test_clock_regression(self):
        store,_=make_epoch();store.clock=lambda:'2026-09-18T00:00:00Z'
        self.assert_code('CLOCK_REGRESSION',store.ingest,self.payload,epoch_id='two',source_url=self.policy.source_url)

    def test_failed_refresh_no_stale(self):
        store,e=make_epoch();store.clock=lambda:'2026-09-20T00:00:00Z'
        self.assert_code('SOURCE_ACQUISITION_FAILED',store.ingest,None,epoch_id='two',source_url=self.policy.source_url)
        self.assert_code('NO_CURRENT_EPOCH',store.require_current)
        self.assertEqual(e,store.epochs[0]);self.assertTrue(verify_chain(store.events))

    def test_epoch_id_reuse(self):
        store,_=make_epoch();store.clock=lambda:'2026-09-20T00:00:00Z'
        self.assert_code('EPOCH_ID_REUSED',store.ingest,self.payload,epoch_id='one',source_url=self.policy.source_url)

    def test_raw_query_parameter(self):
        real_connect=sqlite3.connect;calls=[]
        class RecordingConnection(sqlite3.Connection):
            def execute(self,sql,parameters=()):
                if 'docs MATCH' in sql:calls.append((sql,parameters))
                return super().execute(sql,parameters)
        with patch('sqlite3.connect',side_effect=lambda *a,**kw:real_connect(*a,**kw,factory=RecordingConnection)):
            with backend() as b:
                raw='  remote OR python  '
                self.assertEqual('SUCCESS',b.search(SearchRequest('fixture-a',1,raw)).state)
        self.assertEqual([(QUERY_SQL,(raw,10))],calls)

    def test_invalid_query_no_rewrite(self):
        with backend() as b:
            r=b.search(SearchRequest('fixture-a',1,'"unfinished'))
            self.assertEqual('FAILED',r.state);self.assertEqual('FTS_QUERY_FAILED',r.error_code)
            self.assertEqual('"unfinished',json.loads(r.provenance_json)['query'])
            self.assertEqual(1,json.loads(r.provenance_json)['match_attempts'])
            self.assertEqual('SUCCESS',b.search(SearchRequest('fixture-a',2,'python')).state)

    def test_sql_injection_safe(self):
        with backend() as b:
            result=b.search(SearchRequest('fixture-a',1,"x'; DROP TABLE docs; --"))
            self.assertEqual('FAILED',result.state)
            self.assertTrue(b.search(SearchRequest('fixture-a',2,'python')).results)

    def test_one_attempt_each(self):
        with backend() as b:
            for i in range(1,5):b.search(SearchRequest('fixture-a',i,'python'))
            self.assertEqual(4,sum(e['match_attempts'] for e in b.provenance))
            self.assertTrue(all(e['automatic_retries']==0 for e in b.provenance))

    def test_deterministic_ties(self):
        # Equal title/body; same score must sort by opaque item identity.
        item='<item><guid>{}</guid><title>same</title><description>python</description><link>https://source.example.invalid/jobs/{}</link></item>'
        payload=('<rss><channel>'+item.format('z','z')+item.format('a','a')+'</channel></rss>').encode()
        _,e=make_epoch(payload)
        with backend(e) as b:
            r=b.search(SearchRequest('fixture-a',1,'python'))
            self.assertEqual(['a','z'],[x.item_id for x in r.results])
            self.assertEqual(r.results[0].score,r.results[1].score)

    def test_entrant_exchange(self):
        with backend() as b:
            a=b.search(SearchRequest('fixture-a',1,'remote'))
            c=b.search(SearchRequest('fixture-b',1,'remote'))
            self.assertEqual(a.results,c.results)

    def test_same_epoch_results(self):
        _,e=make_epoch()
        with backend(e) as a,backend(e) as b:
            self.assertEqual(a.search(SearchRequest('fixture-a',1,'python')).results,
                             b.search(SearchRequest('fixture-b',1,'python')).results)

    def test_budget_limit(self):
        with backend() as b:
            for i in range(1,5):self.assertEqual('SUCCESS',b.search(SearchRequest('fixture-a',i,'python')).state)
            r=b.search(SearchRequest('fixture-a',5,'python'))
            self.assertEqual('CALL_BUDGET_EXHAUSTED',r.error_code)
            self.assertEqual(0,json.loads(r.provenance_json)['match_attempts'])

    def test_sequence_and_unknown_entrant(self):
        with backend() as b:
            self.assertEqual('UNKNOWN_ENTRANT',b.search(SearchRequest('other',1,'python')).error_code)
            self.assertEqual('CALL_SEQUENCE_REJECTED',b.search(SearchRequest('fixture-a',True,'python')).error_code)
            self.assertEqual('CALL_SEQUENCE_REJECTED',b.search(SearchRequest('fixture-a',2,'python')).error_code)

    def test_result_limit(self):
        item='<item><guid>{}</guid><title>python</title><link>https://source.example.invalid/jobs/{}</link></item>'
        payload=('<rss><channel>'+''.join(item.format(i,i) for i in range(30))+'</channel></rss>').encode()
        _,e=make_epoch(payload)
        with backend(e) as b:self.assertEqual(10,len(b.search(SearchRequest('fixture-a',1,'python')).results))

    def test_runtime_drift(self):
        _,e=make_epoch();identity=runtime_identity();identity['sqlite_version']='different'
        self.assert_code('RUNTIME_DRIFT',ControlledSourceRetriever,e,clock=lambda:'2026-09-19T00:00:00Z',expected_runtime=identity)

    def test_config_drift(self):
        cfg=copy.deepcopy(self.config);cfg['query']['tokenizer']='porter'
        self.assert_code('CONFIG_DRIFT',assemble,cfg,self.fixture)
        cfg=copy.deepcopy(self.config);cfg['budget']['automatic_retries']=1
        self.assert_code('CONFIG_DRIFT',assemble,cfg,self.fixture)

    def test_claims_and_source_no_auto_admission(self):
        cfg=copy.deepcopy(self.config);cfg['production_source']['admission']='ADMITTED'
        self.assert_code('SOURCE_ADMISSION_NOT_AUTHORIZED',assemble,cfg,self.fixture)
        cfg=copy.deepcopy(self.config);cfg['claims']=['ABSOLUTE_RECALL']
        self.assert_code('CLAIMS_REJECTED',assemble,cfg,self.fixture)

    def test_normalized_provenance(self):
        with backend() as b:
            r=b.search(SearchRequest('fixture-a',1,'python'));p=json.loads(r.provenance_json)
            self.assertEqual(len(r.results),p['result_count'])
            self.assertEqual([digest(asdict(x)) for x in r.results],p['result_fingerprints'])
            self.assertEqual(b.epoch.fingerprint,p['epoch_fingerprint'])
            self.assertEqual(digest(b.config),p['config_fingerprint'])

    def test_hash_chain(self):
        package=assemble(self.config,self.fixture)
        self.assertTrue(verify_chain(package['ingest-events.json']))
        queries=package['query-provenance.json']
        for epoch_id in ('synthetic-epoch-1','synthetic-epoch-2'):
            self.assertTrue(verify_chain([q for q in queries if q['epoch_id']==epoch_id]))
        damaged=copy.deepcopy(package['ingest-events.json']);damaged[0]['record_count']=999
        self.assertFalse(verify_chain(damaged))

    def test_manifest_inputs(self):
        self.assertEqual(assemble(self.config,self.fixture),assemble(self.config,self.fixture))
        self.assertEqual(16,assemble(self.config,self.fixture)['resource-receipt.json']['search_attempts'])

    def test_r1_r8_not_prefilled(self):
        q=qualification({},source_hashes={})
        self.assertTrue(all(v['status']=='UNKNOWN' for v in q['criteria'].values()))
        self.assertEqual('NOT_F1_ELIGIBLE',q['production_f1_eligibility'])
        self.assertEqual('NOT_RUN',q['live_validation'])

    def test_criterion_failure_and_missing_evidence(self):
        records={n:{'id':n,'status':'PASS'} for ns in REQUIREMENTS.values() for n in ns}
        hashes=dict.fromkeys(PATHS,'0'*64)
        q=qualification(records,source_hashes=hashes)
        self.assertEqual('PASS',q['offline_mechanism_result'])
        self.assertEqual('NOT_F1_ELIGIBLE',q['production_f1_eligibility'])
        records['test_raw_query_parameter']['status']='FAIL'
        self.assertEqual('FAIL',qualification(records,source_hashes=hashes)['criteria']['R1']['status'])
        del records['test_no_network_secret']
        self.assertEqual('UNKNOWN',qualification(records,source_hashes=hashes)['criteria']['R2']['status'])

    def test_no_network_secret(self):
        with patch('socket.create_connection',side_effect=AssertionError('network denied')), \
             patch('socket.socket.connect',side_effect=AssertionError('network denied')), \
             patch('socket.getaddrinfo',side_effect=AssertionError('DNS denied')), \
             patch('os.getenv',side_effect=AssertionError('secret lookup denied')), \
             patch.object(os._Environ,'__getitem__',side_effect=AssertionError('environment denied')):
            package=assemble(self.config,self.fixture)
        r=package['resource-receipt.json']
        self.assertEqual(0,r['network_calls']+r['credential_reads']+r['real_source_acquisitions'])

    def test_import_boundary(self):
        for path in PATHS[:3]:
            tree=ast.parse((ROOT/path).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node,(ast.Import,ast.ImportFrom)):
                    modules=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or '']
                    self.assertFalse(any(n.split('.')[0] in {'os','subprocess','socket','requests','httpx','pathlib'} or n=='urllib.request' for n in modules))
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):
                    self.assertNotIn(node.func.id,{'open','eval','exec','__import__'})


    def test_invalid_source_port_is_typed(self):
        self.assert_code('SOURCE_POLICY_REJECTED', SourcePolicy,
                         source_url='https://source.example.invalid:bad/jobs/rss')

    def test_invalid_clock_clears_current(self):
        store, e = make_epoch()
        store.clock = lambda: 'not a timestamp'
        self.assert_code('INVALID_OBSERVATION_TIME', store.ingest, self.payload,
                         epoch_id='two', source_url=self.policy.source_url)
        self.assert_code('NO_CURRENT_EPOCH', store.require_current)
        self.assertIsNone(store.events[-1]['time'])
        self.assertTrue(verify_chain(store.events))
        self.assertEqual([e], store.epochs)

    def test_failed_clock_clears_current(self):
        store, _ = make_epoch()
        def fail(): raise RuntimeError('untrusted diagnostic')
        store.clock = fail
        self.assert_code('CLOCK_FAILED', store.ingest, self.payload,
                         epoch_id='two', source_url=self.policy.source_url)
        self.assert_code('NO_CURRENT_EPOCH', store.require_current)

    def test_runtime_binding_mutation_rejected(self):
        with backend() as r:
            r.config['max_calls'] = 99
            response = r.search(SearchRequest('fixture-a', 1, 'python'))
        self.assertEqual('RETRIEVER_BINDING_DRIFT', response.error_code)
        self.assertEqual(0, json.loads(response.provenance_json)['match_attempts'])

    def test_query_before_epoch_rejected(self):
        with backend() as r:
            r.clock = lambda: '2026-09-18T23:59:59Z'
            response = r.search(SearchRequest('fixture-a', 1, 'python'))
        self.assertEqual('QUERY_BEFORE_EPOCH', response.error_code)

    def test_invalid_request_payload_stays_content_safe(self):
        with backend() as r:
            response = r.search(SearchRequest('fixture-a', 1, object()))
        self.assertEqual('QUERY_CONTRACT_REJECTED', response.error_code)
        self.assertIsNone(json.loads(response.provenance_json)['query'])


class RecordedResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.records={}
    def addSuccess(self,test):
        super().addSuccess(test);self.records[test._testMethodName]={'id':test._testMethodName,'status':'PASS'}
    def addFailure(self,test,err):
        super().addFailure(test,err);self.records[test._testMethodName]={'id':test._testMethodName,'status':'FAIL'}
    def addError(self,test,err):
        super().addError(test,err);self.records[test._testMethodName]={'id':test._testMethodName,'status':'FAIL'}


def write_evidence(output: str) -> int:
    def git(*args):
        return subprocess.run(['git',*args],cwd=ROOT,check=True,capture_output=True,text=True).stdout.strip()
    head=git('rev-parse','HEAD');tree=git('rev-parse','HEAD^{tree}')
    if git('rev-parse',BASE+'^{tree}')!=BASE_TREE:
        raise RuntimeError('BASE_TREE_DRIFT')
    git('merge-base','--is-ancestor',BASE,head)
    changed=git('diff','--name-status',BASE,head).splitlines()
    if sorted(changed)!=sorted('A\t'+p for p in PATHS):
        raise RuntimeError('EIGHT_PATH_SCOPE_VIOLATION')
    if git('status','--porcelain','--untracked-files=no'):
        raise RuntimeError('DIRTY_SOURCE')
    for p in PATHS:
        if git('ls-tree',BASE,'--',p):raise RuntimeError('BASE_PATH_ALREADY_EXISTS')
    hashes={p:sha256((ROOT/p).read_bytes()).hexdigest() for p in PATHS}
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=RecordedResult).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(CSLiveTests))
    config,fixture=inputs()
    with patch('socket.create_connection',side_effect=AssertionError('network denied')), \
         patch('socket.socket.connect',side_effect=AssertionError('network denied')), \
         patch('socket.getaddrinfo',side_effect=AssertionError('DNS denied')), \
         patch('os.getenv',side_effect=AssertionError('secret lookup denied')), \
         patch.object(os._Environ,'__getitem__',side_effect=AssertionError('environment denied')):
        files=assemble(config,fixture)
    files['source-evidence.json']={'base':BASE,'base_tree':BASE_TREE,'head':head,'tree':tree,'file_sha256':hashes,'changed_paths':list(PATHS)}
    files['test-records.json']=result.records
    files['r1-r8.json']=qualification(result.records,source_hashes=hashes)
    files['qualification-receipt.json']={
        'work_order':'WO-ENG-B1-SC-V23-T6-CSLIVE-OFFLINE-01 v0.1','head':head,'tree':tree,
        'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
        'component_tests':'PASS' if result.wasSuccessful() else 'FAIL',
        'source_admission':'NOT_ADMITTED','f1_qualification':'NOT_F1_ELIGIBLE','independent_qa':'PENDING',
        'live_validation':'NOT_RUN','real_source_acquisitions':0,'automatic_retries':0,'formal_execution':False,
        'claims':['SYNTHETIC_OFFLINE_COMPONENT_VALIDATION_ONLY'],
        'fixture_fingerprint':digest(fixture),'config_fingerprint':digest(config)}
    destination=Path(output).resolve()
    if destination==ROOT or ROOT in destination.parents:raise RuntimeError('ARTIFACT_MUST_BE_OUTSIDE_REPO')
    destination.mkdir(parents=True,exist_ok=False)
    for name,value in files.items():
        with (destination/name).open('x',encoding='utf-8') as f:f.write(canonical(value)+'\n')
    (destination/'focused-tests.log').write_text(stream.getvalue(),encoding='utf-8')
    manifest=''.join(sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(destination.iterdir()))
    (destination/'MANIFEST.sha256').write_text(manifest,encoding='utf-8')
    print(stream.getvalue());print(canonical(files['qualification-receipt.json']))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    if '--artifact' in sys.argv:
        parser=argparse.ArgumentParser();parser.add_argument('--artifact',required=True)
        raise SystemExit(write_evidence(parser.parse_args().artifact))
    unittest.main()
