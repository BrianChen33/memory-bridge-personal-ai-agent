"""GitHub transport tests using fake HTTP responses exclusively."""
import base64
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from memory_bridge.core import Denied, Invalid, MAX_BYTES
from memory_bridge.github import GitHubTransport, NoRedirect
from memory_bridge.sync import Conflict

REPO = 'synthetic-owner/private-memory'
BASE = 'https://api.github.com/repos/' + REPO
PATH = 'alice/muse/events.json'
SHA = 'a' * 40
NEW_SHA = 'b' * 40
PRIVATE = {'private': True, 'full_name': REPO}


class FakeResponse:
    def __init__(self, value, url=None, raw=None):
        self.raw = json.dumps(value).encode() if raw is None else raw
        self.url = url
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def geturl(self): return self.url
    def read(self, limit): return self.raw[:limit]


class FakeOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
    def open(self, request, timeout):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError('Unexpected HTTP request')
        response = self.responses.pop(0)
        if isinstance(response, Exception): raise response
        if response.url is None: response.url = request.full_url
        return response


def remote(events=None, **changes):
    raw = json.dumps([] if events is None else events).encode()
    value = dict(type='file', encoding='base64', size=len(raw), sha=SHA,
                 content=base64.b64encode(raw).decode())
    value.update(changes)
    return value


class GitHubTests(unittest.TestCase):
    def transport(self, *responses, write=True):
        opener = FakeOpener(*responses)
        transport = GitHubTransport(REPO, 'synthetic-not-a-real-token',
                                    network_consent=True, write_consent=write, opener=opener)
        return transport, opener

    def test_no_network_consent_or_token_rejected_before_network(self):
        with patch('urllib.request.build_opener') as build:
            for token, consent in (('fake', False), ('', True), (None, True),
                                   ('bad\ntoken', True), ('bad\rtoken', True)):
                with self.subTest(token=token, consent=consent), self.assertRaises(Denied):
                    GitHubTransport(REPO, token, network_consent=consent)
            build.assert_not_called()

    def test_truthy_non_boolean_network_consent_rejected(self):
        with patch('urllib.request.build_opener') as build:
            for consent in (1, 'false', 'true', [True], {'yes': True}):
                with self.subTest(consent=consent), self.assertRaises(Denied):
                    GitHubTransport(REPO, 'fake', network_consent=consent)
            build.assert_not_called()

    def test_non_string_repository_name_fail_closed(self):
        for name in (None, 1, [], {}):
            transport, opener = self.transport(FakeResponse({'private': True, 'full_name': name}))
            with self.subTest(name=name), self.assertRaises(Denied):
                transport.verify_private()
            self.assertEqual(1, len(opener.requests))

    def test_large_wrapper_duplicate_keys_and_nonfinite_rejected(self):
        padding = ' ' * (MAX_BYTES + 1)
        for payload in ('{"private":false,"private":true}', '{"x":NaN}', '{"x":Infinity}'):
            transport, _ = self.transport(FakeResponse(None, raw=(padding + payload).encode()))
            with self.subTest(payload=payload), self.assertRaises(Invalid):
                transport.verify_private()

    def test_upload_schema_and_path_scope_checked_before_network(self):
        good = dict(id='event1', owner='alice', source='muse', fact='fact1', revision=1,
                    op='put', category='project_fact', text='Synthetic data', timestamp=2000000000,
                    expires=None, provenance='Synthetic fixture')
        for item in ({'text': 'bad schema'}, dict(good, owner='bob'),
                     dict(good, source='dot'), dict(good, extra='bad')):
            transport, opener = self.transport()
            with self.subTest(item=item), self.assertRaises(Invalid):
                transport.compare_and_swap(PATH, SHA, [item])
            self.assertEqual([], opener.requests)

    def test_repository_path_escape_rejected(self):
        for repo in ('../evil', 'owner/repo/contents', 'https://evil/repo', 'a/b?x=y', 'a/b#x'):
            with self.subTest(repo=repo), self.assertRaises(Invalid):
                GitHubTransport(repo, 'fake', network_consent=True)

    def test_private_repository_verification(self):
        transport, opener = self.transport(FakeResponse(PRIVATE))
        self.assertTrue(transport.verify_private())
        request = opener.requests[0]
        self.assertEqual(BASE, request.full_url)
        self.assertEqual('GET', request.method)
        self.assertEqual('Bearer synthetic-not-a-real-token', request.get_header('Authorization'))

    def test_public_unknown_wrong_repository_fail_closed(self):
        for value in ({'private': False, 'full_name': REPO}, {}, None,
                      {'private': 1, 'full_name': REPO},
                      {'private': True, 'full_name': 'another/repo'}):
            transport, opener = self.transport(FakeResponse(value))
            with self.subTest(value=value), self.assertRaises(Denied):
                transport.read(PATH)
            self.assertEqual(1, len(opener.requests))

    def test_read_checks_private_then_decodes(self):
        data = [{'synthetic': 'untrusted data'}]
        transport, opener = self.transport(FakeResponse(PRIVATE), FakeResponse(remote(data)))
        self.assertEqual((SHA, data), transport.read(PATH))
        self.assertEqual([BASE, BASE + '/contents/memory-v1/' + PATH],
                         [r.full_url for r in opener.requests])

    def test_missing_file_is_empty(self):
        error = urllib.error.HTTPError(BASE, 404, 'Not Found', {}, io.BytesIO())
        transport, _ = self.transport(FakeResponse(PRIVATE), error)
        self.assertEqual((None, []), transport.read(PATH))

    def test_no_write_consent_rejected_before_network(self):
        transport, opener = self.transport(write=False)
        with self.assertRaises(Denied): transport.compare_and_swap(PATH, SHA, [])
        self.assertEqual([], opener.requests)

    def test_cas_put_contains_expected_sha_and_exact_payload(self):
        events = [dict(id='event1', owner='alice', source='muse', fact='fact1', revision=1, op='put', category='project_fact', text='Synthetic data only', timestamp=2000000000, expires=None, provenance='Synthetic fixture')]
        transport, opener = self.transport(FakeResponse(PRIVATE),
                                          FakeResponse({'content': {'sha': NEW_SHA}}))
        self.assertEqual(NEW_SHA, transport.compare_and_swap(PATH, SHA, events))
        request = opener.requests[-1]
        self.assertEqual('PUT', request.method)
        body = json.loads(request.data)
        self.assertEqual(SHA, body['sha'])
        self.assertEqual(events, json.loads(base64.b64decode(body['content'])))

    def test_create_omits_expected_sha(self):
        transport, opener = self.transport(FakeResponse(PRIVATE), FakeResponse({'content': {'sha': NEW_SHA}}))
        transport.compare_and_swap(PATH, None, [])
        self.assertNotIn('sha', json.loads(opener.requests[-1].data))

    def test_conflict_never_retries(self):
        for code in (409, 422):
            error = urllib.error.HTTPError(BASE, code, 'Conflict', {}, io.BytesIO())
            transport, opener = self.transport(FakeResponse(PRIVATE), error)
            with self.subTest(code=code), self.assertRaises(Conflict):
                transport.compare_and_swap(PATH, SHA, [])
            self.assertEqual(2, len(opener.requests))

    def test_unconfirmed_write_reports_uncertain_outcome(self):
        transport, opener = self.transport(FakeResponse(PRIVATE), FakeResponse({}))
        with self.assertRaisesRegex(Invalid, 'uncertain'):
            transport.compare_and_swap(PATH, SHA, [])
        self.assertEqual(2, len(opener.requests))

    def test_path_escape_rejected_before_network(self):
        for path in ('../muse/events.json', 'alice/../../events.json', '/alice/muse/events.json',
                     'alice/muse/other.json', 'alice/muse/events.json?x=1', 'alice\\muse\\events.json'):
            transport, opener = self.transport()
            with self.subTest(path=path), self.assertRaises(Denied): transport.read(path)
            self.assertEqual([], opener.requests)

    def test_redirect_handler_rejects_redirect(self):
        with self.assertRaises(Denied):
            NoRedirect().redirect_request(None, None, 302, 'redirect', {}, 'https://elsewhere.invalid')

    def test_response_url_mismatch_rejected(self):
        transport, _ = self.transport(FakeResponse(PRIVATE, url='https://elsewhere.invalid'))
        with self.assertRaises(Denied): transport.verify_private()

    def test_default_opener_has_no_proxy_and_no_redirect(self):
        with patch('urllib.request.build_opener', return_value=FakeOpener()) as build:
            GitHubTransport(REPO, 'fake', network_consent=True)
        handlers = build.call_args.args
        self.assertTrue(any(isinstance(h, NoRedirect) for h in handlers))
        proxies = [h for h in handlers if isinstance(h, __import__('urllib.request', fromlist=['ProxyHandler']).ProxyHandler)]
        self.assertEqual({}, proxies[0].proxies)

    def test_remote_response_size_bound(self):
        transport, _ = self.transport(FakeResponse(None, raw=b' ' * 1_500_001))
        with self.assertRaisesRegex(Invalid, 'size limit'): transport.verify_private()

    def test_remote_file_metadata_and_size_bounds(self):
        for changes in ({'size': -1}, {'size': MAX_BYTES + 1}, {'size': True}, {'size': 999},
                        {'encoding': 'none'}, {'type': 'dir'}, {'sha': 'bad'}, {'content': None}):
            transport, _ = self.transport(FakeResponse(PRIVATE), FakeResponse(remote(**changes)))
            with self.subTest(changes=changes), self.assertRaises(Invalid): transport.read(PATH)

    def test_malformed_base64_and_non_list_rejected(self):
        for value in (remote(content='@@@'), remote(content='A'), remote(events={'not': 'list'})):
            transport, _ = self.transport(FakeResponse(PRIVATE), FakeResponse(value))
            with self.subTest(value=value), self.assertRaises(Invalid): transport.read(PATH)

    def test_upload_bounds_and_sha_rejected_before_network(self):
        for expected, data in (('bad', []), (SHA, {}), (SHA, [None] * 1001),
                               (SHA, ['x' * MAX_BYTES])):
            transport, opener = self.transport()
            with self.subTest(expected=expected, count=len(data)), self.assertRaises(Invalid):
                transport.compare_and_swap(PATH, expected, data)
            self.assertEqual([], opener.requests)

    def test_put_network_failure_is_uncertain_and_never_retried(self):
        for error in (urllib.error.URLError('synthetic network failure'),
                      TimeoutError('synthetic timeout'), OSError('synthetic socket error'),
                      urllib.error.HTTPError(BASE, 503, 'unavailable', {}, io.BytesIO())):
            transport, opener = self.transport(FakeResponse(PRIVATE), error)
            with self.subTest(error=type(error).__name__), self.assertRaisesRegex(Invalid, 'uncertain'):
                transport.compare_and_swap(PATH, SHA, [])
            self.assertEqual(2, len(opener.requests))
            self.assertEqual(['GET', 'PUT'], [r.method for r in opener.requests])

    def test_network_and_http_errors_are_redacted(self):
        for error in (urllib.error.URLError('secret-like test detail'),
                      urllib.error.HTTPError(BASE, 403, 'secret-like test detail', {}, io.BytesIO())):
            transport, _ = self.transport(error)
            with self.assertRaises(Denied) as caught: transport.verify_private()
            self.assertNotIn('secret-like', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
