"""Loopback proxy for Cloudflare; the application enforces individual accounts."""
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask
HOP={'connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailer','transfer-encoding','upgrade'}
@asynccontextmanager
async def lifespan(app):
    app.state.client=httpx.AsyncClient(timeout=httpx.Timeout(120,connect=10),follow_redirects=False,trust_env=False)
    yield
    await app.state.client.aclose()
app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
@app.middleware('http')
async def headers(request,call_next):
    response=await call_next(request)
    response.headers['Cache-Control']='private, no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    return response
@app.get('/__gateway/login')
async def old_login():return RedirectResponse('/',status_code=303)
@app.api_route('/{path:path}',methods=['GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'])
async def proxy(request:Request,path:str):
    if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('origin')!='https://'+request.headers.get('host',''):
        return JSONResponse({'detail':'Invalid origin'},status_code=403)
    headers={k:v for k,v in request.headers.items() if k.lower() not in HOP|{'host','authorization','origin','forwarded','x-forwarded-host','x-forwarded-proto','x-forwarded-for','cf-access-jwt-assertion'}}
    if 'origin' in request.headers:headers['origin']='http://127.0.0.1'
    target=httpx.URL('http://127.0.0.1:80/').copy_with(raw_path=request.scope['raw_path']+(b'?'+request.scope['query_string'] if request.scope['query_string'] else b''))
    try:upstream=await app.state.client.send(app.state.client.build_request(request.method,target,headers=headers,content=request.stream()),stream=True)
    except httpx.RequestError:return JSONResponse({'detail':'Library is restarting. Please retry shortly.'},status_code=503)
    response=StreamingResponse(upstream.aiter_raw(),status_code=upstream.status_code,background=BackgroundTask(upstream.aclose))
    response.raw_headers=[(k,v) for k,v in upstream.headers.raw if k.decode().lower() not in HOP]
    return response
