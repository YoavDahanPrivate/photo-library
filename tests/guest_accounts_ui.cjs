const {chromium}=require(process.argv[2]||'playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 for(const viewport of [{width:1440,height:900},{width:390,height:844}]){
 const page=await browser.newPage({viewport});let active=null;const errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{const req=route.request(),u=new URL(req.url()),p=u.pathname;requests.push(p);
 if(p.startsWith('/api/')){let json=[];
 if(p==='/api/auth/me'){if(!active)return route.fulfill({status:401,json:{detail:'Please sign in'}});json=active;}
 else if(p==='/api/auth/login'){const user=req.postDataJSON().username;active={id:user,name:user==='guest'?'Guest':'Drora',must_change:user==='drora',theme:'sage',source_ids:null,source_names:null};json=active;}
 else if(p==='/api/auth/logout'){active=null;json={ok:true};}
 else if(p==='/api/status')json={revision:1,total:0,counts:{ready:0},features:{}};
 else if(p==='/api/sync/status')json={running:false,runs:[]};
 else if(p==='/api/media')json={items:[],total:0};
 else if(p==='/api/library/hierarchy')json={databases:[],sources:[],linked_sources:[]};
 else if(p==='/api/place-options')json={options:[]};
 else if(p==='/api/people/operations/current')json=null;
 return route.fulfill({json});
 }
 const file=path.resolve(__dirname,'../frontend/dist','.'+(p==='/'?'/index.html':p));try{return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'});}catch{return route.fulfill({status:404,body:''});}
 });
 await page.goto('https://dahanphotos.com/');
 await page.getByLabel('Your account').selectOption('drora');
 assert(await page.getByRole('button',{name:'Sign in with Face ID / fingerprint'}).isVisible());
 await page.getByLabel('Your account').selectOption('guest');
 assert.equal(await page.getByRole('button',{name:'Sign in with Face ID / fingerprint'}).count(),0);
 await page.getByLabel('Password',{exact:true}).fill('Guest123456');await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await page.getByTitle('Account settings').click();
 await page.getByRole('heading',{name:'Guest account',exact:true}).waitFor();
 assert.equal(await page.getByLabel('New password',{exact:true}).count(),0);
 assert.equal(await page.getByRole('button',{name:'Enable Face ID / fingerprint'}).count(),0);
 assert(!requests.some(p=>p.startsWith('/api/auth/passkeys')));
 await page.getByRole('button',{name:'Sign out / switch user'}).click();
 await page.getByLabel('Your account').selectOption('drora');await page.getByLabel('Password',{exact:true}).fill('Drora1919');await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await page.getByRole('heading',{name:'Choose your own password'}).waitFor();
 assert.deepEqual(errors,[]);console.log('PASS',viewport.width,'Drora sign-in and Guest password-only account UI');await page.close();
 }
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
