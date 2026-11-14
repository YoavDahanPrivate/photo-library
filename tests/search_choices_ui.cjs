const {chromium}=require(process.argv[2]||process.env.PLAYWRIGHT_MODULE||'playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const artifactDir=fs.mkdtempSync(path.join(require('os').tmpdir(),'dahan-ui-'));const root=path.join(__dirname,'../frontend/dist');
const server=http.createServer((req,res)=>{const file=path.join(root,new URL(req.url,'http://local').pathname==='/'?'index.html':new URL(req.url,'http://local').pathname);try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({channel:'msedge',headless:true});try{
for(const viewport of [{width:1440,height:900},{width:1920,height:1080},{width:390,height:844},{width:320,height:640}]){
 const page=await browser.newPage({viewport,reducedMotion:'reduce',hasTouch:viewport.width<=760,isMobile:viewport.width<=760});const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.clock.install();let job={id:'fixture',state:'completed',phase:'Matches ready for review',started_at:Date.now()/1000-60,finished_at:Date.now()/1000,updated_at:Date.now()/1000,result:{suggestions:1}};let releaseMedia;const mediaGate=new Promise(resolve=>releaseMedia=resolve);let releaseNeighbors;const neighborsGate=new Promise(resolve=>releaseNeighbors=resolve);let releaseDetail;const detailGate=new Promise(resolve=>releaseDetail=resolve);let offsetSeen=0;const imageRequests=[];
 await page.route('**/api/**',async route=>{const u=new URL(route.request().url()),p=u.pathname;let json=[];
 if(p==='/api/auth/me')json={id:'qa',name:'QA',theme:'light',source_ids:null,source_names:null};
 else if(p==='/api/status')json={revision:1,total:240,counts:{ready:240},features:{}};
 else if(p==='/api/sync/status')json={running:false,runs:[]};
 else if(p==='/api/library/hierarchy')json={databases:[],sources:[],linked_sources:[]};
 else if(p==='/api/sources')json=[{phone:'Fixture',album:'LongAlbumNameWithoutSpaces'.repeat(8),count:240},{phone:'Other phone',album:'Album',count:2}];
 else if(p==='/api/search/validate')json={valid:true};
 else if(p==='/api/media'){await mediaGate;const offset=Number(u.searchParams.get('offset')||0);offsetSeen=Math.max(offsetSeen,offset);json={total:240,items:Array.from({length:Math.min(80,240-offset)},(_,i)=>({id:'m'+(offset+i),name:'Photo '+i,phone:'Fixture',album:'Album',kind:'photo',taken:'2020-01-01',width:800,height:600,people_names:[]}))};}
 else if(/^\/api\/media\/m\d+\/neighbors$/.test(p)){const n=Number(p.split('/')[3].slice(1));const rows=Array.from({length:5},(_,i)=>Math.max(0,n-2)+i).filter(i=>i<240).map(i=>({id:'m'+i,previous:i?'m'+(i-1):null,next:i<239?'m'+(i+1):null,position:i+1,total:240}));json={...rows.find(r=>r.id==='m'+n),window:rows};}
 else if(/^\/api\/media\/m\d+$/.test(p)){const id=p.split('/')[3];json={id,name:'Photo '+id,phone:'Fixture',album:'Album',kind:'photo',taken:'2020-01-01',width:800,height:600,people_names:[],faces:[],metadata:{},duration:null,latitude:null,longitude:null};}
 else if(p.endsWith('/display-original')){imageRequests.push(u.href);return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1200"><rect width="1600" height="1200" fill="#aca"/></svg>'});}
 else if(p.includes('/thumbnail')){imageRequests.push(u.href);return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#abc"/></svg>'});}
 else if(p==='/api/people/operations/current')json=job;
 else if(p==='/api/people')json=[{id:1,name:'Maya',count:9,photo_count:2,cover:'portrait'},{id:2,name:'Daniel',count:4,photo_count:4,cover:'portrait2'}];
 else if(p==='/api/people/suggestions')json=[{face_id:'f',person_id:1,name:'Maya',score:.9,confidence:'high'}];
 else if(p==='/api/place-options')json={options:[{id:'country:test',label:'Testland',kind:'country',country:'Testland'},{id:'city:test',label:'Sample city',kind:'city',country:'Testland'}]};
 else if(p.includes('/matching'))json={};
 await route.fulfill({json});});

 releaseMedia();
 await page.goto('http://127.0.0.1:'+server.address().port);
 await page.locator('.media-tile').first().waitFor();
 await page.getByRole('button',{name:'Search library'}).click();
 await page.getByLabel('Search helpers').getByRole('button',{name:'Albums',exact:true}).click();
 assert(await page.locator('.helper-options label').evaluateAll(rows=>rows.every(e=>e.scrollWidth<=e.clientWidth+1)),'Album labels fit their cards');
 await page.getByLabel('Search helpers').getByRole('button',{name:'People',exact:true}).click();
 await page.locator('.helper-options .search-person-thumbnail').first().waitFor();
 assert.equal(await page.locator('.helper-options .search-person-thumbnail').first().getAttribute('src'),'/api/faces/portrait2/thumbnail');
 const helpers=page.getByLabel('Search helpers');
 assert.equal(await helpers.getByRole('button',{name:'Media',exact:true}).count(),0);
 const names=()=>page.locator('.helper-options .search-option-text').allTextContents();
 assert.deepEqual(await names(),['Daniel4 photos','Maya2 photos']);
 await page.getByLabel('People view by').selectOption('popularity');
 assert.deepEqual(await names(),['Maya2 photos','Daniel4 photos']);
 await page.getByLabel('People sort order').selectOption('descending');
 assert.deepEqual(await names(),['Daniel4 photos','Maya2 photos']);
 await page.getByLabel('People view by').selectOption('alphabet');
 assert.deepEqual(await names(),['Maya2 photos','Daniel4 photos']);
 await helpers.getByRole('button',{name:'Places',exact:true}).click();
 await page.getByLabel('Place view filter').selectOption('country');
 await page.locator('.helper-options label').filter({hasText:'Testland'}).waitFor();
 assert.equal(await page.locator('.helper-options label').count(),1);
 await page.locator('.helper-options input').check();
 await page.getByLabel('Place view filter').selectOption('city');
 assert.equal(await page.locator('.helper-options label').count(),1);
 assert((await page.locator('.helper-options').innerText()).includes('Sample city'));
 await page.getByLabel('Place view filter').selectOption('country');
 assert(await page.locator('.helper-options input').isChecked());
 await helpers.getByRole('button',{name:'Albums',exact:true}).click();
 assert.equal(await page.getByLabel('Media type',{exact:true}).count(),0);
 assert.equal(await page.getByLabel('Image orientation',{exact:true}).count(),0);
 await helpers.getByRole('button',{name:'Examples',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Search examples'});
 await dialog.waitFor();
 assert.equal(await dialog.locator('li').count(),10);
 assert(await dialog.evaluate(e=>e.scrollWidth<=e.clientWidth+1));
 assert(await dialog.locator('.search-examples-content').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
 await page.keyboard.press('Escape');
 await dialog.waitFor({state:'hidden'});
 assert(await helpers.getByRole('button',{name:'Examples',exact:true}).evaluate(e=>e===document.activeElement));
 const input=page.getByRole('combobox',{name:'Search photos'});
 await input.fill('Maya');
 await page.locator('.search-suggestions .search-person-thumbnail').waitFor();
 await input.fill('Aug 2024');
 await page.getByRole('option',{name:'Aug 2024 Entire month'}).waitFor();
 const validation=page.waitForRequest(r=>r.url().includes('/api/search/validate'));
 await input.press('Enter');
 assert.equal(new URL((await validation).url()).searchParams.get('expression'),'in Aug 2024');
 assert.deepEqual(errors,[]);
 console.log('PASS',viewport.width,'album wrapping, person thumbnails, month search submission');
 await page.close();
}
}finally{await browser.close();server.close();}})().catch(e=>{console.error(e);process.exitCode=1;server.close();});
