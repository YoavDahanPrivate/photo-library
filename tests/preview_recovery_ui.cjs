const {chromium}=require(process.argv[2]||process.env.PLAYWRIGHT_MODULE||'playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const artifactDir=fs.mkdtempSync(path.join(require('os').tmpdir(),'dahan-ui-'));const root=path.join(__dirname,'../frontend/dist');
const server=http.createServer((req,res)=>{const file=path.join(root,new URL(req.url,'http://local').pathname==='/'?'index.html':new URL(req.url,'http://local').pathname);try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({channel:'msedge',headless:true});try{
for(const viewport of [{width:1440,height:900},{width:1920,height:1080},{width:390,height:844},{width:320,height:640}]){
 const page=await browser.newPage({viewport,reducedMotion:'reduce',hasTouch:viewport.width<=760,isMobile:viewport.width<=760});const errors=[];page.setDefaultTimeout(8000);page.on('pageerror',e=>errors.push(e.message));await page.clock.install();let job={id:'fixture',state:'completed',phase:'Matches ready for review',started_at:Date.now()/1000-60,finished_at:Date.now()/1000,updated_at:Date.now()/1000,result:{suggestions:1}};let releaseMedia;const mediaGate=new Promise(resolve=>releaseMedia=resolve);let releaseNeighbors;const neighborsGate=new Promise(resolve=>releaseNeighbors=resolve);let releaseDetail;const detailGate=new Promise(resolve=>releaseDetail=resolve);let offsetSeen=0;const imageRequests=[];
 let preparationFails=true,releaseVideo;const videoStall=new Promise(resolve=>releaseVideo=resolve);let failure='error',releaseStall;const stall=new Promise(resolve=>releaseStall=resolve);
 await page.route('**/api/**',async route=>{const u=new URL(route.request().url()),p=u.pathname;let json=[];
 if(p==='/api/auth/me')json={id:'qa',name:'QA',theme:'light',source_ids:null,source_names:null};
 else if(p==='/api/status')json={revision:1,total:240,counts:{ready:240},features:{}};
 else if(p==='/api/sync/status')json={running:false,runs:[]};
 else if(p==='/api/library/hierarchy')json={databases:[],sources:[],linked_sources:[]};
 else if(p==='/api/sources')json=[{phone:'Fixture',album:'LongAlbumNameWithoutSpaces'.repeat(8),count:240},{phone:'Other phone',album:'Album',count:2}];
 else if(p==='/api/search/validate')json={valid:true};
 else if(p==='/api/media'){await mediaGate;const offset=Number(u.searchParams.get('offset')||0);offsetSeen=Math.max(offsetSeen,offset);json={total:240,items:Array.from({length:Math.min(80,240-offset)},(_,i)=>({id:'m'+(offset+i),name:'Photo '+i,phone:'Fixture',album:'Album',kind:i===1?'video':'photo',taken:'2020-01-01',width:800,height:600,people_names:[]}))};}
 else if(/^\/api\/media\/m\d+\/neighbors$/.test(p)){const n=Number(p.split('/')[3].slice(1));const rows=Array.from({length:5},(_,i)=>Math.max(0,n-2)+i).filter(i=>i<240).map(i=>({id:'m'+i,previous:i?'m'+(i-1):null,next:i<239?'m'+(i+1):null,position:i+1,total:240}));json={...rows.find(r=>r.id==='m'+n),window:rows};}
 else if(/^\/api\/media\/m\d+$/.test(p)){const id=p.split('/')[3];json={id,name:'Photo '+id,phone:'Fixture',album:'Album',kind:id==='m1'?'video':'photo',taken:'2020-01-01',width:800,height:600,people_names:[],faces:[],metadata:{},duration:null,latitude:null,longitude:null};}
 else if(p.endsWith('/display-original')){imageRequests.push(u.href);return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1200"><rect width="1600" height="1200" fill="#aca"/></svg>'});}
 else if(p==='/api/media/m1/preview'&&route.request().method()==='POST'){return preparationFails?route.fulfill({status:503,json:{detail:'Preview preparation unavailable'}}):route.fulfill({json:{url:'/api/media/m1/preview'}});}
 else if(p==='/api/media/m1/preview'){await videoStall;return route.fulfill({status:503,body:'Video unavailable'});}
 else if(p.includes('/thumbnail')&&['large','small'].includes(u.searchParams.get('size'))&&failure!=='ok'){if(failure==='stall')await stall;else return route.fulfill({status:503,body:'Unavailable'});return route.fulfill({status:503,body:'Unavailable'});}
 else if(p.includes('/thumbnail')){imageRequests.push(u.href);return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#abc"/></svg>'});}
 else if(p==='/api/people/operations/current')json=job;
 else if(p==='/api/people')json=[{id:1,name:'Maya',count:9,photo_count:2,cover:'portrait'},{id:2,name:'Daniel',count:4,photo_count:4,cover:'portrait2'}];
 else if(p==='/api/people/suggestions')json=[{face_id:'f',person_id:1,name:'Maya',score:.9,confidence:'high'}];
 else if(p==='/api/place-options')json={options:[{id:'country:test',label:'Testland',kind:'country',country:'Testland'},{id:'city:test',label:'Sample city',kind:'city',country:'Testland'}]};
 else if(p.includes('/matching'))json={};
 await route.fulfill({json});});


 releaseMedia();await page.goto('http://127.0.0.1:'+server.address().port);await page.locator('.media-tile').first().waitFor();
 await page.locator('.photo-card').first().click();
 const error=page.locator('.preview-recovery');await error.waitFor();assert((await error.innerText()).includes('could not be loaded'));
 failure='ok';await error.getByRole('button',{name:'Retry preview'}).click();await error.waitFor({state:'hidden'});
 await page.waitForFunction(()=>{const img=document.querySelector('.incoming-frame img');return img?.complete&&img.naturalWidth>0});
 await page.clock.runFor(16000);assert.equal(await error.count(),0,'Loaded image must not get a late timeout error');
 await page.getByRole('button',{name:'Close viewer',exact:true}).click();
 failure='stall';await page.locator('.photo-card').nth(2).click();await page.locator('.media-loading').waitFor();await page.clock.runFor(16000);await error.waitFor();assert((await error.innerText()).includes('taking too long'));
 failure='ok';await error.getByRole('button',{name:'Retry preview'}).click();await error.waitFor({state:'hidden'});await page.getByRole('button',{name:'Close viewer',exact:true}).click();releaseStall();
 await page.locator('[data-media-id="m1"] .photo-card').click();await page.getByRole('button',{name:'Play video preview',exact:true}).click();await error.waitFor();assert((await error.innerText()).includes('Preview preparation unavailable'));
 preparationFails=false;await error.getByRole('button',{name:'Retry preview'}).click();await page.locator('.incoming-frame video').waitFor();await page.clock.runFor(21000);await error.waitFor();assert((await error.innerText()).includes('video is taking too long'));releaseVideo();
 assert(await page.getByRole('button',{name:'Retry preview'}).isVisible());assert(await page.getByRole('button',{name:'Close viewer',exact:true}).isVisible());
 await page.getByRole('button',{name:'Close viewer',exact:true}).click();await page.locator('.viewer-overlay').waitFor({state:'hidden'});
 assert.deepEqual(errors,[]);console.log('PASS',viewport.width,'failed images, stalled image timeout, retry recovery and visible video failure');await page.close();
}
}finally{await browser.close();server.close();}})().catch(e=>{console.error(e);process.exitCode=1;server.close();});
