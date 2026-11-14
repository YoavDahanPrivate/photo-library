const {chromium}=require(process.argv[2]||process.env.PLAYWRIGHT_MODULE||'playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const artifactDir=fs.mkdtempSync(path.join(require('os').tmpdir(),'dahan-ui-'));const root=path.join(__dirname,'../frontend/dist');
const server=http.createServer((req,res)=>{const file=path.join(root,new URL(req.url,'http://local').pathname==='/'?'index.html':new URL(req.url,'http://local').pathname);try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({channel:'msedge',headless:true});try{
for(const viewport of [{width:1440,height:900},{width:390,height:844}]){
 const page=await browser.newPage({viewport,reducedMotion:'reduce',hasTouch:viewport.width<=760,isMobile:viewport.width<=760});const errors=[];page.setDefaultTimeout(7000);page.on('pageerror',e=>{errors.push(e.message);console.log('PAGE ERROR',e.stack)});await page.clock.install();let job={id:'fixture',state:'completed',phase:'Matches ready for review',started_at:Date.now()/1000-60,finished_at:Date.now()/1000,updated_at:Date.now()/1000,result:{suggestions:1}};let releaseMedia;const mediaGate=new Promise(resolve=>releaseMedia=resolve);let releaseNeighbors;const neighborsGate=new Promise(resolve=>releaseNeighbors=resolve);let releaseDetail;const detailGate=new Promise(resolve=>releaseDetail=resolve);let offsetSeen=0;const imageRequests=[];
 let identity='qa';const accounts={qa:null,other:null};
 await page.route('**/api/**',async route=>{const u=new URL(route.request().url()),p=u.pathname;let json=[];
 if(p.endsWith('/people-preferences')&&route.request().method()==='PUT'){assert(!('selection' in route.request().postDataJSON()),'Selection must never be sent to the database');accounts[identity]=route.request().postDataJSON();json={people_browse:accounts[identity]};}
 else if(p==='/api/auth/me')json={people_browse:accounts[identity],id:identity,name:'QA',theme:'light',source_ids:null,source_names:null};
 else if(p==='/api/status')json={revision:1,total:240,counts:{ready:240},features:{}};
 else if(p==='/api/sync/status')json={running:false,runs:[],settings:{frequency:'daily',time:'02:00',weekday:0,month_day:1,timezone:'Asia/Jerusalem',auto_assign:false},next_due:null};
 else if(p==='/api/duplicates/status')json={jobs:[],reviews:[],trash_count:0};
 else if(p==='/api/sync/assignments')json={faces:[],actions:[]};
 else if(p==='/api/library/hierarchy')json={databases:[],sources:[],linked_sources:[]};
 else if(p==='/api/sources')json=[{phone:'Fixture',album:'Album',count:240},{phone:'Other phone',album:'Album',count:2}];
 else if(p==='/api/search/validate')json={valid:true};
 else if(p==='/api/media'){await mediaGate;const offset=Number(u.searchParams.get('offset')||0);offsetSeen=Math.max(offsetSeen,offset);json={total:240,items:Array.from({length:Math.min(Number(u.searchParams.get("limit")||80),240-offset)},(_,i)=>({id:'m'+(offset+i),name:'Photo '+i,phone:'Fixture',album:'Album',kind:offset+i===81?'video':'photo',taken:'2020-01-01',width:800,height:600,people_names:[]}))};}
 else if(/^\/api\/media\/m\d+\/neighbors$/.test(p)){const n=Number(p.split('/')[3].slice(1));const rows=Array.from({length:5},(_,i)=>Math.max(0,n-2)+i).filter(i=>i<240).map(i=>({id:'m'+i,previous:i?'m'+(i-1):null,next:i<239?'m'+(i+1):null,position:i+1,total:240}));json={...rows.find(r=>r.id==='m'+n),window:rows};}
 else if(/^\/api\/media\/m\d+$/.test(p)){const id=p.split('/')[3];json={id,name:'Photo '+id,phone:'Fixture',album:'Album',kind:id==='m81'?'video':'photo',taken:'2020-01-01',width:800,height:600,people_names:[],faces:[],metadata:{},duration:null,latitude:null,longitude:null};}
 else if(p.endsWith('/display-original')){imageRequests.push(u.href);return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1200"><rect width="1600" height="1200" fill="#aca"/></svg>'});}
 else if(p.includes('/thumbnail')){imageRequests.push(u.href);return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#abc"/></svg>'});}
 else if(p==='/api/people/operations/current')json=job;
 else if(p==='/api/people')json=[{id:1,name:'Maya',count:2,cover:'a'},{id:2,name:'Maya',count:9,cover:'b'},{id:3,name:'Alice',count:20,cover:'c'},{id:4,name:null,count:3,cover:'d'},{id:-1,name:'Unknown People',count:8,cover:'e'},{id:0,name:'Unassigned faces',count:1,cover:'f'}];
 else if(p==='/api/people/suggestions')json=[{face_id:'f',person_id:1,name:'Maya',score:.9,confidence:'high'}];
 else if(p==='/api/place-options')json={options:[]};
 else if(p.includes('/matching'))json={};
 await route.fulfill({json});});

 releaseMedia();
 const visit=async()=>{await page.goto('http://127.0.0.1:'+server.address().port);await page.locator('.media-tile').first().waitFor();};
 const enterPeople=async()=>{await page.getByRole('button',{name:/^People\s*\d*$/}).click();await page.locator('.people-grid').waitFor();};
 const card=id=>page.locator('[data-person-card="'+id+'"] .person-card');
 const action=page.getByLabel('People action');
 const unknown=page.getByRole('button',{name:'Unknown people',exact:true});
 const expectSearch=async(work,expression)=>{
   const request=page.waitForRequest(r=>new URL(r.url()).pathname==='/api/media'&&new URL(r.url()).searchParams.get('expression')===expression);
   await work();await request;await page.locator('.media-tile').first().waitFor();assert.equal(await page.locator('.people-grid').count(),0);
 };
 await visit();await enterPeople();
 assert.equal(await action.inputValue(),'search');assert.equal(await unknown.getAttribute('aria-pressed'),'false');
 assert.equal(await page.locator('[data-person-card]').count(),3);
 assert.equal(await page.locator('.people-grid input[type=checkbox]').count(),0);
 assert.equal(await page.getByRole('region',{name:'Select unnamed groups'}).count(),0);

 let validationCount=0;page.on('request',r=>{if(new URL(r.url()).pathname==='/api/search/validate')validationCount++;});
 const cdp=viewport.width<=760?await page.context().newCDPSession(page):null;
 const pressPortrait=async(id,{move=false,cancel=false}={})=>{
   await card(id).scrollIntoViewIfNeeded();const box=await card(id).locator('img').boundingBox(),x=box.x+box.width/2,y=box.y+box.height/2;
   if(cdp)await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});
   else {await page.mouse.move(x,y);await page.mouse.down();}
   if(move){if(cdp)await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+35,y}]});else await page.mouse.move(x+35,y);}
   if(cancel){if(cdp)await cdp.send('Input.dispatchTouchEvent',{type:'touchCancel',touchPoints:[]});else await card(id).dispatchEvent('pointercancel',{pointerId:1});}
   await page.clock.runFor(650);
   // Keep holding after the mode change; release must not become a click elsewhere.
   await page.clock.runFor(700);
   if(!cancel&&cdp)await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
   else if(!cdp)await page.mouse.up();
 };
 await pressPortrait(1,{move:true});assert.equal(await page.getByRole('button',{name:'Exit selection mode'}).count(),0);assert.equal(validationCount,0);
 await pressPortrait(1,{cancel:true});assert.equal(await page.getByRole('button',{name:'Exit selection mode'}).count(),0);assert.equal(validationCount,0);
 await pressPortrait(1);await page.getByRole('button',{name:'Exit selection mode'}).waitFor();
 assert(await page.locator('[data-person-card="1"] input[type=checkbox]').isChecked());
 assert.equal(await page.locator('.people-grid input:checked').count(),1);assert.equal(validationCount,0);
 await card(2).click();assert.equal(await page.locator('.people-grid input:checked').count(),2);
 await pressPortrait(2);await page.getByRole('button',{name:'Select people',exact:true}).waitFor();
 assert.equal(await page.locator('.people-grid input[type=checkbox]').count(),0);assert.equal(validationCount,0);assert.equal(accounts.qa,null);
 await expectSearch(()=>card(1).click(),'Includes("Maya [#1]")');
 await enterPeople();await page.getByRole('button',{name:'Select people',exact:true}).click();
 assert.equal(await page.locator('.people-grid input[type=checkbox]').count(),3);
 await card(1).click();await card(2).click();
 const selected=page.getByRole('region',{name:'Find photos with selected people'});
 await selected.getByText('2 selected',{exact:true}).waitFor();
 await selected.getByRole('button',{name:'Deselect all'}).click();assert(await selected.getByRole('button',{name:'Find photos',exact:true}).isDisabled());
 await card(1).click();await card(2).click();
 await expectSearch(()=>selected.getByRole('button',{name:'Find photos',exact:true}).click(),'Includes("Maya [#2]" and "Maya [#1]")');
 await enterPeople();assert.equal(await page.getByRole('button',{name:'Select people',exact:true}).count(),1);await page.getByRole('button',{name:'Select people',exact:true}).click();
 await unknown.click();await card(4).click();await unknown.click();await selected.getByText('0 selected',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Exit selection mode'}).click();
 await unknown.click();await expectSearch(()=>card(-1).click(),'Includes("Unknown People [#-1]")');
 await enterPeople();await action.selectOption('edit');await page.getByRole('region',{name:'Select unnamed groups'}).waitFor();
 await card(1).click();await page.getByLabel('Person name',{exact:true}).waitFor();
 await page.getByRole('button',{name:'All people',exact:true}).click();
 await unknown.click();assert.equal(await page.getByRole('region',{name:'Select unnamed groups'}).count(),0);
 await action.selectOption('search');await page.getByRole('button',{name:'Select people',exact:true}).click();const savedEdit=page.waitForResponse(r=>r.url().includes('/people-preferences')&&r.request().postDataJSON()?.action==='edit'&&!('selection' in r.request().postDataJSON()));await action.selectOption('edit');
 // Ensure the queued account writes finish before simulating another device.
 await savedEdit;
 await page.evaluate(()=>localStorage.clear());await visit();await enterPeople();assert.equal(await action.inputValue(),'edit');assert.equal(await unknown.getAttribute('aria-pressed'),'false');
 await action.selectOption('search');assert.equal(await page.getByRole('button',{name:'Select people',exact:true}).count(),1);assert(!('selection' in accounts.qa));
 identity='other';await visit();await enterPeople();assert.equal(await action.inputValue(),'search');assert.equal(await unknown.getAttribute('aria-pressed'),'false');assert.equal(await page.getByRole('button',{name:'Select people',exact:true}).count(),1);
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);
 console.log('PASS',viewport.width,'long-press entry/exit, cancelled gestures, no release search, direct search, multi-select, edit flow and account isolation');await page.close();
}
}finally{await browser.close();server.close();}})().catch(e=>{console.error(e);process.exitCode=1;server.close();});
