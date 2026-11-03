"""Explicitly enabled GitHub Contents transport. Never invoked automatically."""
import base64
import json
import re
import urllib.error
import urllib.request
from .core import Invalid, Denied, canonical, strict_json, MAX_BYTES, validate
from .sync import Conflict

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise Denied('redirect refused')

class GitHubTransport:
    def __init__(self,repository,token,*,network_consent=False,write_consent=False,opener=None):
        if not isinstance(repository,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}/[A-Za-z0-9_.-]{1,100}',repository): raise Invalid('repository format')
        if network_consent is not True or not isinstance(token,str) or not token or '\n' in token or '\r' in token: raise Denied('explicit network consent and token required')
        self.repository=repository; self._token=token; self.write_consent=write_consent is True
        self._opener=opener or urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def _request(self,suffix,method='GET',data=None):
        request=urllib.request.Request('https://api.github.com/repos/'+self.repository+suffix,data=None if data is None else canonical(data).encode(),method=method,headers={'Authorization':'Bearer '+self._token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json','User-Agent':'external-memory-bridge/0.1'})
        try:
            with self._opener.open(request,timeout=20) as response:
                if response.geturl()!=request.full_url: raise Denied('response URL mismatch')
                raw=response.read(1_500_001)
                if len(raw)>1_500_000: raise Invalid('response size limit')
                return strict_json(raw, max_bytes=1_500_000)
        except urllib.error.HTTPError as exc:
            if exc.code==404: return None
            if exc.code in (409,422): raise Conflict('GitHub CAS conflict') from None
            raise Denied('write outcome uncertain; inspect before retry' if method=='PUT' else 'GitHub request rejected') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise Denied('write outcome uncertain; inspect before retry' if method=='PUT' else 'GitHub request failed') from None
    def verify_private(self):
        metadata=self._request('')
        if not isinstance(metadata,dict) or metadata.get('private') is not True or not isinstance(metadata.get('full_name'),str) or metadata['full_name'].casefold()!=self.repository.casefold(): raise Denied('repository must be verified private')
        return True
    def _path(self,path):
        if not isinstance(path,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}/[A-Za-z0-9_-]{1,64}/events.json',path): raise Denied('dedicated path required')
        return '/contents/memory-v1/'+path
    def read(self,path):
        suffix=self._path(path); self.verify_private(); result=self._request(suffix)
        if result is None: return None,[]
        if not isinstance(result,dict) or result.get('type')!='file' or result.get('encoding')!='base64' or type(result.get('size')) is not int or not 0<=result['size']<=MAX_BYTES: raise Invalid('invalid remote file')
        sha=result.get('sha'); content=result.get('content')
        if not isinstance(sha,str) or not re.fullmatch(r'[0-9a-f]{40}',sha) or not isinstance(content,str): raise Invalid('remote SHA/content')
        try: raw=base64.b64decode(''.join(content.split()),validate=True)
        except ValueError as exc: raise Invalid('remote encoding') from exc
        if len(raw)!=result['size']: raise Invalid('remote size mismatch')
        events=strict_json(raw)
        if not isinstance(events,list): raise Invalid('remote event list')
        return sha,events
    def compare_and_swap(self,path,expected,events):
        if not self.write_consent: raise Denied('explicit write consent required')
        suffix=self._path(path)
        if expected is not None and (not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{40}',expected)): raise Invalid('expected SHA')
        raw=canonical(events).encode()
        if not isinstance(events,list) or len(events)>1000 or len(raw)>MAX_BYTES: raise Invalid('upload limit')
        owner,source,_=path.split('/')
        for event in events:
            validate(event)
            if event['owner']!=owner or event['source']!=source: raise Denied('event path scope')
        self.verify_private()
        data={'message':'Append approved external memory events','content':base64.b64encode(raw).decode()}
        if expected is not None: data['sha']=expected
        response=self._request(suffix,'PUT',data)
        if not isinstance(response,dict) or not isinstance(response.get('content'),dict) or not re.fullmatch(r'[0-9a-f]{40}',str(response['content'].get('sha',''))): raise Invalid('write outcome uncertain; inspect before retry')
        return response['content']['sha']
