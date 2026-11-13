import importlib.util
from pathlib import Path
import httpx
from fastapi.testclient import TestClient
spec=importlib.util.spec_from_file_location('account_gateway',Path(__file__).parents[1]/'scripts/password_gateway.py')
gateway=importlib.util.module_from_spec(spec);spec.loader.exec_module(gateway)
def test_gateway_preserves_account_cookies_and_rejects_cross_origin():
    seen=[]
    def upstream(request):
        seen.append(request)
        return httpx.Response(200,headers=[('set-cookie','dahan_account=test; Secure; HttpOnly; SameSite=Strict; Path=/'),('set-cookie','dahan_passkey_flow=flow; Secure; HttpOnly; Path=/')],stream=httpx.ByteStream(b'{}'))
    with TestClient(gateway.app,base_url='https://dahanphotos.com') as c:
        gateway.app.state.client=httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        assert c.post('/api/auth/login',headers={'origin':'https://evil.invalid'}).status_code==403
        r=c.post('/api/auth/login',headers={'origin':'https://dahanphotos.com'},json={})
        assert r.status_code==200 and len(r.headers.get_list('set-cookie'))==2
        assert c.get('/api/media?limit=2').status_code==200
        assert 'dahan_account=test' in seen[-1].headers['cookie']
        assert seen[-1].url.query==b'limit=2'
        assert seen[0].headers['origin']=='http://127.0.0.1'
        assert seen[0].headers['host']=='127.0.0.1'
