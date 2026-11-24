const {chromium}=require(process.argv[2]);
const fs=require('fs'),path=require('path'),assert=require('assert/strict'),crypto=require('crypto');
const root=path.resolve(__dirname,'../frontend/dist');
const credentialId=crypto.randomBytes(24),challenge=crypto.randomBytes(32);
const privateKey=crypto.generateKeyPairSync('ec',{namedCurve:'prime256v1'}).privateKey.export({format:'der',type:'pkcs8'}).toString('base64');
const profile=id=>({id,name:id[0].toUpperCase()+id.slice(1),must_change:false,theme:'sage',source_ids:null,source_names:null});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  async function fixture({remembered='yoav',mobile=true,behavior='success',enabled=true,session=null}={}){
   const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:900},isMobile:mobile,hasTouch:mobile});
   const page=await context.newPage();const errors=[],requests=[];let active=session,selected=remembered||'yoav';
   page.on('pageerror',e=>errors.push(e.message));
   await page.addInitScript(({remembered,behavior})=>{
    if(!sessionStorage.getItem('fixture-initialized')){if(remembered)localStorage.setItem('dahan.profile',remembered);sessionStorage.setItem('fixture-initialized','1');}
    window.credentialCalls=0;window.credentialAborts=0;
    const original=navigator.credentials.get.bind(navigator.credentials);
    navigator.credentials.get=async options=>{
     window.credentialCalls++;
     if(behavior==='failOnce'&&window.credentialCalls===1)throw new DOMException('Cancelled','NotAllowedError');
     if(behavior==='pending')return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>{window.credentialAborts++;reject(new DOMException('Cancelled','AbortError'));},{once:true}));
     return original(options);
    };
   },{remembered,behavior});
   const cdp=await context.newCDPSession(page);await cdp.send('WebAuthn.enable');
   const {authenticatorId}=await cdp.send('WebAuthn.addVirtualAuthenticator',{options:{protocol:'ctap2',transport:'internal',hasResidentKey:true,hasUserVerification:true,isUserVerified:true,automaticPresenceSimulation:true}});
   await cdp.send('WebAuthn.addCredential',{authenticatorId,credential:{credentialId:credentialId.toString('base64'),isResidentCredential:true,rpId:'dahanphotos.com',privateKey,userHandle:Buffer.from(remembered||'yoav').toString('base64'),signCount:0}});
   await page.route('**/*',async route=>{
    const req=route.request(),u=new URL(req.url()),p=u.pathname;requests.push(p);
    if(p.startsWith('/api/')){
     let json=[];
     if(p==='/api/auth/me'){if(!active)return route.fulfill({status:401,json:{detail:'Please sign in.'}});json=active;}
     else if(p==='/api/auth/passkeys/login/options'){
      selected=req.postDataJSON().username;
      if(!enabled)return route.fulfill({status:400,json:{detail:'Sign in with your password to enable a passkey first.'}});
      json={challenge:challenge.toString('base64url'),rpId:'dahanphotos.com',userVerification:'required',allowCredentials:[{type:'public-key',id:credentialId.toString('base64url')}]};
     }else if(p==='/api/auth/passkeys/login/verify'){
      const credential=req.postDataJSON().credential;
      assert.equal(credential.id,credentialId.toString('base64url'));
      assert(credential.response.signature&&credential.response.authenticatorData,'Browser must return a signed assertion');
      active=profile(selected);json=active;
     }else if(p==='/api/auth/login'){active=profile(req.postDataJSON().username);json=active;}
     else if(p==='/api/auth/logout'){active=null;json={ok:true};}
     else if(p==='/api/status')json={revision:1,total:0,counts:{ready:0},features:{}};
     else if(p==='/api/sync/status')json={running:false,runs:[]};
     else if(p==='/api/media')json={items:[],total:0};
     else if(p==='/api/library/hierarchy')json={databases:[],sources:[],linked_sources:[]};
     else if(p==='/api/place-options')json={options:[]};
     else if(p==='/api/people/operations/current')json=null;
     return route.fulfill({json});
    }
    const file=path.resolve(root,'.'+(p==='/'?'/index.html':p));
    try{return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.json')?'application/json':'text/html'});}catch{return route.fulfill({status:404,body:''});}
   });
   await page.goto('https://dahanphotos.com/');
   return {page,context,errors,requests,close:async()=>{assert.deepEqual(errors,[]);await context.close();}};
  }
  {
   const f=await fixture();await f.page.getByTitle('Account settings').waitFor();
   assert.equal(await f.page.evaluate(()=>window.credentialCalls),1);
   assert.equal(await f.page.evaluate(()=>localStorage.getItem('dahan.profile')),'yoav');
   console.log('PASS remembered mobile account signs in automatically with verified-device assertion');
   await f.page.getByTitle('Account settings').click();await f.page.getByRole('button',{name:'Sign out / switch user',exact:true}).click();
   await f.page.getByLabel('Your account').waitFor();await f.page.reload();await f.page.getByLabel('Your account').waitFor();
   assert.equal(await f.page.evaluate(()=>window.credentialCalls),0,'Explicit logout must not automatically sign the user back in');
   await f.close();
  }
  {
   const f=await fixture({behavior:'failOnce'});
   await f.page.getByRole('button',{name:'Try Face ID / fingerprint again',exact:true}).waitFor();
   assert(await f.page.getByRole('button',{name:'Use password',exact:true}).isVisible());
   assert(await f.page.getByRole('button',{name:'Sign out / switch user',exact:true}).isVisible());
   await f.page.getByRole('button',{name:'Try Face ID / fingerprint again',exact:true}).click();
   await f.page.getByTitle('Account settings').waitFor();assert.equal(await f.page.evaluate(()=>window.credentialCalls),2);
   console.log('PASS failure offers all three choices; retry succeeds');await f.close();
  }
  {
   const f=await fixture({remembered:'hila',behavior:'pending'});
   await f.page.waitForFunction(()=>window.credentialCalls===1);
   await f.page.getByRole('button',{name:'Use password',exact:true}).click();
   assert.equal(await f.page.getByLabel('Your account').inputValue(),'hila');
   assert.equal(await f.page.evaluate(()=>window.credentialAborts),1);
   await f.page.getByLabel('Password',{exact:true}).fill('fixture password');await f.page.getByRole('button',{name:'Sign in',exact:true}).click();
   await f.page.getByTitle('Account settings').waitFor();assert(!f.requests.includes('/api/auth/passkeys/login/verify'));
   console.log('PASS password fallback cancels biometric prompt and retains the account');await f.close();
  }
  {
   const f=await fixture({behavior:'pending'});await f.page.waitForFunction(()=>window.credentialCalls===1);
   await f.page.getByRole('button',{name:'Sign out / switch user',exact:true}).click();
   await f.page.waitForFunction(()=>!localStorage.getItem('dahan.profile'));
   assert.equal(await f.page.getByLabel('Your account').inputValue(),'');
   assert.equal(await f.page.evaluate(()=>window.credentialAborts),1);
   await f.page.getByLabel('Your account').selectOption('hila');await f.page.getByLabel('Password',{exact:true}).fill('fixture password');await f.page.getByRole('button',{name:'Sign in',exact:true}).click();
   await f.page.getByTitle('Account settings').waitFor();assert.equal(await f.page.evaluate(()=>localStorage.getItem('dahan.profile')),'hila');
   console.log('PASS switch user cancels prompt, signs out and remembers the newly authenticated user');await f.close();
  }
  for(const options of [{enabled:false},{remembered:''},{remembered:'guest'},{mobile:false},{session:profile('yoav')}]){
   const f=await fixture(options);
   if(options.session)await f.page.getByTitle('Account settings').waitFor();else await f.page.getByLabel('Your account').waitFor();
   assert.equal(await f.page.evaluate(()=>window.credentialCalls),0);
   console.log('PASS no automatic prompt',JSON.stringify(options));await f.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
