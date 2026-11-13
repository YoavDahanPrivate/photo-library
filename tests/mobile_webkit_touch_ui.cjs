const {webkit}=require(process.argv[2]||process.env.PLAYWRIGHT_MODULE||'playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const artifactDir=fs.mkdtempSync(path.join(require('os').tmpdir(),'dahan-ui-'));const root=path.join(__dirname,'../frontend/dist');
const server=http.createServer((req,res)=>{const file=path.join(root,new URL(req.url,'http://local').pathname==='/'?'index.html':new URL(req.url,'http://local').pathname);try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await webkit.launch({headless:true});try{
for(const viewport of [{width:390,height:844}]){
 const page=await browser.newPage({viewport,reducedMotion:'reduce',hasTouch:viewport.width<=760,isMobile:viewport.width<=760});const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.clock.install();let job={id:'fixture',state:'completed',phase:'Matches ready for review',started_at:Date.now()/1000-60,finished_at:Date.now()/1000,updated_at:Date.now()/1000,result:{suggestions:1}};let releaseMedia;const mediaGate=new Promise(resolve=>releaseMedia=resolve);let releaseNeighbors;const neighborsGate=new Promise(resolve=>releaseNeighbors=resolve);let releaseDetail;const detailGate=new Promise(resolve=>releaseDetail=resolve);let offsetSeen=0;const imageRequests=[];
 await page.route('**/api/**',async route=>{const u=new URL(route.request().url()),p=u.pathname;let json=[];
 if(p==='/api/auth/me')json={id:'qa',name:'QA',theme:'light',source_ids:null,source_names:null};
 else if(p==='/api/status')json={revision:1,total:240,counts:{ready:240},features:{}};
 else if(p==='/api/sync/status')json={running:false,runs:[]};
 else if(p==='/api/library/hierarchy')json={databases:[],sources:[],linked_sources:[]};
 else if(p==='/api/sources')json=[{phone:'Fixture',album:'Album',count:240},{phone:'Other phone',album:'Album',count:2}];
 else if(p==='/api/search/validate')json={valid:true};
 else if(p==='/api/media'){await mediaGate;const offset=Number(u.searchParams.get('offset')||0);offsetSeen=Math.max(offsetSeen,offset);json={total:240,items:Array.from({length:Math.min(80,240-offset)},(_,i)=>({id:'m'+(offset+i),name:'Photo '+i,phone:'Fixture',album:'Album',kind:'photo',taken:'2020-01-01',width:800,height:600,people_names:[]}))};}
 else if(/^\/api\/media\/m\d+\/neighbors$/.test(p)){const n=Number(p.split('/')[3].slice(1));const rows=Array.from({length:5},(_,i)=>Math.max(0,n-2)+i).filter(i=>i<240).map(i=>({id:'m'+i,previous:i?'m'+(i-1):null,next:i<239?'m'+(i+1):null,position:i+1,total:240}));json={...rows.find(r=>r.id==='m'+n),window:rows};}
 else if(/^\/api\/media\/m\d+$/.test(p)){const id=p.split('/')[3];json={id,name:'Photo '+id,phone:'Fixture',album:'Album',kind:'photo',taken:'2020-01-01',width:800,height:600,people_names:[],faces:[],metadata:{},duration:null,latitude:null,longitude:null};}
 else if(p.endsWith('/display-original')){imageRequests.push(u.href);return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1200"><rect width="1600" height="1200" fill="#aca"/></svg>'});}
 else if(p.includes('/thumbnail')){imageRequests.push(u.href);return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#abc"/></svg>'});}
 else if(p==='/api/people/operations/current')json=job;
 else if(p==='/api/people')json=[{id:1,name:'Maya',count:1}];
 else if(p==='/api/people/suggestions')json=[{face_id:'f',person_id:1,name:'Maya',score:.9,confidence:'high'}];
 else if(p==='/api/place-options')json={options:[]};
 else if(p.includes('/matching'))json={};
 await route.fulfill({json});});
 await page.addInitScript(()=>{Object.defineProperty(navigator,'canShare',{configurable:true,value:()=>true});Object.defineProperty(navigator,'share',{configurable:true,value:async data=>{window.__sharedNames=data.files.map(f=>f.name);}});});
 await page.goto('http://127.0.0.1:'+server.address().port);
 await page.locator('.results-loading-banner').waitFor();
 assert.equal(await page.getByText('Loading your moments…',{exact:true}).count(),0);
 assert.equal(await page.locator('.results-loading-banner').count(),1);
 const banner=await page.locator('.results-loading-banner').boundingBox(),top=await page.locator('.library-topbar').boundingBox();
 assert(banner.y>=top.y+top.height+10,'Popup border must clear the complete header');
 assert(banner.x>=0&&banner.x+banner.width<=viewport.width,'Popup must fit viewport');
 assert(await page.locator('.results-loading-banner').evaluate(e=>{const r=e.getBoundingClientRect();e.style.pointerEvents='auto';const hit=!!document.elementFromPoint(r.x+r.width/2,r.y+2)?.closest('.results-loading-banner');e.style.pointerEvents='';return hit}),'Top edge must be unobstructed');
 await page.screenshot({path:path.join(artifactDir,'loading-popup-'+viewport.width+'.png')});
 releaseMedia();await page.locator('.media-tile').first().waitFor();await page.locator('.results-loading-banner').waitFor({state:'hidden'});console.log('PASS',viewport.width,'single popup, full top edge, clears after results');

 const assertClosedMenus=async()=>assert(await page.evaluate(()=>Array.from(document.querySelectorAll('.library-topbar details:not([open]) > :not(summary)')).every(e=>{const r=e.getBoundingClientRect();return getComputedStyle(e).display==='none'&&r.width===0&&r.height===0;})),'Closed menus must have no floating controls');
 await assertClosedMenus();
 await page.getByLabel('Appearance',{exact:true}).click();assert(await page.getByRole('button',{name:'Select photos & videos',exact:true}).isVisible());
 await page.getByLabel('Appearance',{exact:true}).click();await assertClosedMenus();
 console.log('PASS',viewport.width,'closed header menu geometry and appearance toggle');
 assert.equal(await page.getByRole('combobox',{name:'Database',exact:true}).count(),0);
 assert.equal(await page.locator('.master-search-header').isVisible(),false);
 assert.equal(await page.getByRole('button',{name:'Edit dates & locations',exact:true}).isVisible(),false);
 const photo=await page.locator('.media-tile').first().boundingBox();assert(photo.y<350,'Photos must start near the top');
 assert(await page.locator('.library-notification-hint').isVisible());await page.clock.runFor(20100);assert.equal(await page.locator('.library-notification-hint').count(),0);
 await page.getByRole('button',{name:'Notifications',exact:true}).click();await page.getByRole('button',{name:'Review matches',exact:true}).waitFor();
 await page.getByRole('checkbox',{name:"Don't show this message again"}).check();await page.getByRole('button',{name:'Close notifications'}).click();
 await page.reload();await page.locator('.media-tile').first().waitFor();assert.equal(await page.locator('.library-notification-hint').count(),0);
 job={...job,id:'new-job'};await page.clock.runFor(6000);await page.locator('.library-notification-hint').waitFor();await page.clock.runFor(21000);
 if(viewport.width<=760){assert.equal(await page.locator('.gallery-controls').isVisible(),false);await page.getByRole('button',{name:'View options',exact:true}).click();}
 await page.locator('.library-source-picker summary').click();assert(await page.locator('.gallery-controls').evaluate(e=>getComputedStyle(e).overflowY==='visible'),'Toolbar must not clip or scroll menus');assert(await page.locator('.library-source-menu').evaluate(e=>{const r=e.getBoundingClientRect();return document.elementFromPoint(r.x+20,r.bottom-15)?.closest('.library-source-menu')}),'Source menu must be unobstructed');await page.screenshot({path:path.join(artifactDir,'source-menu-'+viewport.width+'.png')});await page.getByRole('checkbox',{name:'Other phone',exact:true}).uncheck();await page.locator('.library-source-picker summary').click();
 if(viewport.width<=760)await page.getByRole('button',{name:'Done',exact:true}).click();
 await page.getByRole('button',{name:'Search library'}).click();
 const search=page.getByRole('combobox',{name:'Search photos'});
 await search.fill('Ma');await page.clock.runFor(100);
 await page.getByRole('option').filter({hasText:'Maya'}).first().tap();
 assert((await search.inputValue()).includes('Maya'),'Touch suggestion selection commits value');

 console.log('PASS WebKit touch autocomplete selection');await page.close();
}
}finally{await browser.close();server.close();}})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
