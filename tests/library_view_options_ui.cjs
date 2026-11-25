const {chromium,webkit}=require(process.argv[2]||process.env.PLAYWRIGHT_MODULE||'playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const artifactDir=fs.mkdtempSync(path.join(require('os').tmpdir(),'dahan-ui-'));const root=path.join(__dirname,'../frontend/dist');
const server=http.createServer((req,res)=>{const file=path.join(root,new URL(req.url,'http://local').pathname==='/'?'index.html':new URL(req.url,'http://local').pathname);try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await (process.env.TEST_WEBKIT?webkit.launch({headless:true}):chromium.launch({...process.env.TEST_CHROMIUM_PATH?{executablePath:process.env.TEST_CHROMIUM_PATH}:{channel:'msedge'},headless:true}));try{
for(const viewport of [{width:390,height:844},{width:1440,height:1000}]){
 const page=await browser.newPage({viewport,reducedMotion:'reduce',hasTouch:viewport.width<=760,isMobile:viewport.width<=760});const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.clock.install();let job={id:'fixture',state:'completed',phase:'Matches ready for review',started_at:Date.now()/1000-60,finished_at:Date.now()/1000,updated_at:Date.now()/1000,result:{suggestions:1}};let failSources=false,emptySources=false;let releaseSources;const sourcesGate=new Promise(resolve=>releaseSources=resolve);let releaseMedia;const mediaGate=new Promise(resolve=>releaseMedia=resolve);let releaseNeighbors;const neighborsGate=new Promise(resolve=>releaseNeighbors=resolve);let releaseDetail;const detailGate=new Promise(resolve=>releaseDetail=resolve);let offsetSeen=0;const imageRequests=[];
 await page.route('**/api/**',async route=>{const u=new URL(route.request().url()),p=u.pathname;let json=[];
 if(p==='/api/auth/me')json={id:'qa',name:'QA',theme:'light',source_ids:null,source_names:null};
 else if(p==='/api/status')json={revision:1,total:240,counts:{ready:240},features:{}};
 else if(p==='/api/sync/status')json={running:false,runs:[]};
 else if(p==='/api/library/hierarchy')json={databases:[],sources:[],linked_sources:[]};
 else if(p==='/api/sources'){await sourcesGate;if(failSources)return route.fulfill({status:503,json:{detail:'Unavailable'}});json=emptySources?[]:[{phone:'Fixture',album:'Album',count:240},{phone:'Other phone',album:'Album',count:2}];}
 else if(p==='/api/search/validate')json={valid:true};
 else if(p==='/api/media'){await mediaGate;const offset=Number(u.searchParams.get('offset')||0);offsetSeen=Math.max(offsetSeen,offset);json={total:240,items:Array.from({length:Math.min(80,240-offset)},(_,i)=>({id:'m'+(offset+i),name:'Photo '+i,phone:'Fixture',album:i%2?'Summer':'Winter',kind:'photo',taken:'2020-01-01',width:800,height:600,people_names:[]}))};}
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

 await page.goto('http://127.0.0.1:'+server.address().port);
 await page.locator('.results-loading-banner').getByText('Loading your sources…',{exact:true}).waitFor();
 await page.clock.runFor(30000);
 assert.equal(await page.getByText('No moments in this view',{exact:true}).count(),0);
 assert.equal(await page.locator('.results-loading-banner').count(),1);
 await page.screenshot({path:path.join(artifactDir,'source-loading.png')});
 releaseSources();await page.getByText('Results loading…',{exact:true}).waitFor();releaseMedia();
 await page.locator('.media-tile').first().waitFor();
 await page.getByRole('button',{name:'View options',exact:true}).click();
 for(const label of ['Sources','Grouped by','Show','Sort order'])assert.equal(await page.getByRole('group',{name:label,exact:true}).count(),1);
 const sourceGroup=page.getByRole('group',{name:'Sources',exact:true}),allSources=sourceGroup.getByRole('button',{name:'All sources',exact:true});
 assert.equal(await allSources.getAttribute('aria-pressed'),'true');
 const allBox=await allSources.boundingBox(),firstBox=await sourceGroup.getByRole('checkbox').first().boundingBox();assert(firstBox.y>=allBox.y+allBox.height,'Individual sources must appear below All sources');
 await sourceGroup.getByRole('checkbox',{name:'Fixture',exact:true}).uncheck();assert.equal(await allSources.getAttribute('aria-pressed'),'false');
 await allSources.click();assert.equal(await allSources.getAttribute('aria-pressed'),'true');for(const checkbox of await sourceGroup.getByRole('checkbox').all())assert(await checkbox.isChecked());
 await allSources.click();assert.equal(await allSources.getAttribute('aria-pressed'),'false');for(const checkbox of await sourceGroup.getByRole('checkbox').all())assert(!(await checkbox.isChecked()));await sourceGroup.getByRole('alert').waitFor();
 await page.screenshot({path:path.join(artifactDir,'no-sources-'+viewport.width+'.png')});
 await sourceGroup.getByRole('checkbox',{name:'Fixture',exact:true}).check();assert.equal(await allSources.getAttribute('aria-pressed'),'false');assert.equal(await sourceGroup.getByRole('alert').count(),0);
 await sourceGroup.getByRole('checkbox',{name:'Other phone',exact:true}).check();assert.equal(await allSources.getAttribute('aria-pressed'),'true');
 await page.locator('.media-tile').first().waitFor();
 await page.getByRole('radio',{name:'Albums',exact:true}).check();
 assert.equal(await page.getByRole('heading',{name:'Fixture · Summer',exact:true}).count(),1);
 assert.equal(await page.getByRole('heading',{name:'Fixture · Winter',exact:true}).count(),1);
 await page.screenshot({path:path.join(artifactDir,'view-options.png')});
 await page.getByRole('button',{name:'Done',exact:true}).click();
 await page.getByLabel('Appearance',{exact:true}).click();await page.getByRole('button',{name:'Select photos & videos',exact:true}).click();
 assert(await page.getByRole('button',{name:'Share / Save',exact:true}).isDisabled());
 await page.getByRole('button',{name:/Select all currently shown/}).click();
 assert(!(await page.getByRole('button',{name:'Share / Save',exact:true}).isDisabled()));
 for(const button of await page.locator('.metadata-tools button').all())assert(await button.evaluate(e=>parseFloat(getComputedStyle(e).borderTopWidth)>=1));
 await page.screenshot({path:path.join(artifactDir,'selection.png')});
 await page.getByRole('button',{name:'Clear selection',exact:true}).click();
 assert(await page.getByRole('button',{name:'Edit dates & locations',exact:true}).isDisabled());
 await page.getByRole('button',{name:'Exit selection',exact:true}).click();assert.equal(await page.locator('.metadata-tools').count(),0);
 assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)));
 failSources=true;await page.reload();await page.getByText('Results could not be loaded',{exact:true}).waitFor();
 assert.equal(await page.locator('.results-loading-banner').count(),0);
 failSources=false;await page.getByRole('button',{name:'Retry loading results',exact:true}).click();await page.locator('.media-tile').first().waitFor();
 emptySources=true;await page.reload();await page.getByText('No moments in this view',{exact:true}).waitFor();assert.equal(await page.locator('.results-loading-banner').count(),0);
 assert.deepEqual(errors,[]);console.log('PASS delayed sources, album groups, view options, selection actions and borders');await page.close();
}
}finally{await browser.close();server.close();}console.log('ARTIFACTS',artifactDir);})().catch(e=>{console.error(e);process.exit(1)});
