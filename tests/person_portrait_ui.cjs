const {chromium}=require(process.argv[2]||'playwright');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../frontend/dist'),output=process.env.DAHAN_QA_OUTPUT||require('os').tmpdir();
fs.mkdirSync(output,{recursive:true});
const server=http.createServer((req,res)=>{const name=new URL(req.url,'http://localhost').pathname,file=path.resolve(root,'.'+(name==='/'?'/index.html':name));if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],writes=[],pages=[];
 page.on('pageerror',error=>errors.push(error.stack));
 let selected=null,stale=false,failLoad=false,unavailable=false;
 const cover=()=>selected||'f000';
 const people=()=>[{id:1,name:'Maya',count:95,cover:cover()},{id:2,name:'Daniel',count:1,cover:'d001'}];
 const settings={frequency:'off',time:'03:00',weekday:0,month_day:1,timezone:'UTC',auto_assign:false};
 const identity=()=>({id:1,name:'Maya',cover:cover(),automatic_cover:'f000',portrait_custom:!!selected});
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),name=url.pathname;let value=[];
  if(name==='/api/people/1/portrait'){
   if(req.method()==='POST'){
    const body=req.postDataJSON();writes.push({name,body});
    if(stale){await route.fulfill({status:409,json:{detail:'That face moved to another person. Refresh the portrait choices.'}});return;}
    selected=body.face_id;value=identity();
   }else{
    if(failLoad){await route.fulfill({status:503,json:{detail:'Fixture storage unavailable'}});return;}
    const offset=Number(url.searchParams.get('offset')||0);pages.push(offset);
    value={person:identity(),total:95,offset,limit:30,items:Array.from({length:Math.min(30,95-offset)},(_,i)=>{const index=offset+i;return {id:'f'+String(index).padStart(3,'0'),media_id:'media-'+index,name:'image-'+String(index).padStart(3,'0')+'.jpg',kind:index%3?'photo':'video',taken:'2020-01-20',timestamp:index+.5,available:index!==5&&!unavailable};})};
   }
  }else if(req.method()!=='GET'){writes.push({name});await route.abort();return;}
  else if(name==='/api/people')value=people();
  else if(name==='/api/people-name-records')value=people().map(p=>({...p,faces:p.count,conflict:false}));
  else if(name==='/api/faces')value=[{id:'f000',media_id:'media-0',person_id:1,timestamp:0,status:'manual'}];
  else if(name==='/api/people/calibration')value={report:null,active_id:null,effective_mode:'conservative'};
  else if(name==='/api/people/operations/current')value=null;
  else if(name==='/api/status')value={revision:0,total:100,counts:{ready:100},faces:96,features:{}};
  else if(name==='/api/sync/status')value={settings,next_due:null,running:false,runs:[]};
  else if(name==='/api/sync/assignments')value={actions:[],faces:[]};
  else if(name==='/api/duplicates/status')value={jobs:[],reviews:[],trash_count:0};
  else if(name==='/api/databases/folders/capabilities')value={available:false};
  else if(name==='/api/library/hierarchy')value={databases:[],sources:[],linked_sources:[]};
  else if(name==='/api/sources')value=[{phone:'Fixture',album:'Album',count:100}];
  else if(name==='/api/media')value={items:[],total:0};
  else if(name==='/api/place-options')value={options:[]};
  else if(name.includes('thumbnail')){await route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><rect width="120" height="120" fill="#e8eee0"/><ellipse cx="60" cy="48" rx="25" ry="30" fill="#afc5a6"/><path d="M15 120 Q15 78 60 78 Q105 78 105 120" fill="#7c9b73"/></svg>'});return;}
  await route.fulfill({json:value});
 });
 const visit=async()=>{await page.goto('http://127.0.0.1:'+server.address().port+'/?fixture='+Date.now());await page.locator('.sidebar nav').getByRole('button',{name:/^People/}).click();await page.locator('[data-person-card="1"] .person-card').waitFor();};
 const open=async()=>{await page.locator('[data-person-card="1"] .person-card').click();await page.getByRole('button',{name:'Choose portrait',exact:true}).click();await page.getByRole('button',{name:'Choose portrait 2: image-001.jpg',exact:true}).waitFor();};
 const dialog=page.getByRole('dialog',{name:'Choose portrait',exact:true});
 await visit();await open();
 assert(await page.locator('#root').evaluate(root=>root.inert));
 assert(await dialog.getByRole('button',{name:'Save portrait',exact:true}).isDisabled());
 assert(await dialog.getByRole('button',{name:'Choose portrait 6: image-005.jpg',exact:true}).isDisabled());
 await dialog.getByRole('button',{name:'Choose portrait 2: image-001.jpg',exact:true}).click();
 assert((await dialog.getByAltText('Portrait preview').getAttribute('src')).includes('f001'));
 await dialog.getByRole('button',{name:'Next ›',exact:true}).click();await dialog.getByRole('button',{name:'Choose portrait 31: image-030.jpg',exact:true}).waitFor();
 assert((await dialog.getByAltText('Portrait preview').getAttribute('src')).includes('f001'));
 await dialog.getByRole('button',{name:'Last »',exact:true}).click();await dialog.getByRole('button',{name:'Choose portrait 94: image-093.jpg',exact:true}).click();
 await dialog.getByRole('button',{name:'Save portrait',exact:true}).click();await dialog.waitFor({state:'hidden'});
 assert.equal(selected,'f093');assert.deepEqual(writes.at(-1),{name:'/api/people/1/portrait',body:{face_id:'f093'}});
 assert((await page.locator('.person-current-portrait').getAttribute('src')).includes('f093'));
 await page.getByRole('button',{name:'All people',exact:true}).click();
 assert((await page.locator('[data-person-card="1"] img').getAttribute('src')).includes('f093'));
 await visit();await open();assert((await dialog.getByAltText('Portrait preview').getAttribute('src')).includes('f093'));
 await dialog.getByRole('button',{name:'Choose portrait 3: image-002.jpg',exact:true}).click();
 await dialog.getByRole('button',{name:'Close portrait picker',exact:true}).focus();await page.keyboard.press('Shift+Tab');
 assert.equal(await page.evaluate(()=>document.activeElement.textContent),'Save portrait');await page.keyboard.press('Tab');
 assert.equal(await page.evaluate(()=>document.activeElement.getAttribute('aria-label')),'Close portrait picker');
 const before=writes.length;await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});assert.equal(writes.length,before);
 assert(!(await page.locator('#root').evaluate(root=>root.inert)));assert.equal(await page.evaluate(()=>document.activeElement.textContent),'Choose portrait');
 // A concurrent reassignment is a visible recoverable conflict, never an assignment.
 await page.getByRole('button',{name:'Choose portrait',exact:true}).click();await dialog.getByRole('button',{name:'Choose portrait 3: image-002.jpg',exact:true}).click();stale=true;
 await dialog.getByRole('button',{name:'Save portrait',exact:true}).click();await dialog.getByRole('alert').filter({hasText:'That face moved'}).waitFor();assert.equal(selected,'f093');
 stale=false;await dialog.getByRole('button',{name:'Refresh choices',exact:true}).click();await dialog.getByRole('button',{name:'Choose portrait 3: image-002.jpg',exact:true}).waitFor();
 await page.screenshot({path:path.join(output,'person-portrait-desktop.png')});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'person-portrait-mobile.png')});
 const bounds=await dialog.boundingBox();assert(bounds.x>=0&&bounds.x+bounds.width<=391&&bounds.y>=0&&bounds.y+bounds.height<=845);
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await dialog.getByRole('button',{name:'Use automatic',exact:true}).click();assert((await dialog.getByAltText('Portrait preview').getAttribute('src')).includes('f000'));
 await dialog.getByRole('button',{name:'Save portrait',exact:true}).click();await dialog.waitFor({state:'hidden'});assert.equal(selected,null);
 await page.setViewportSize({width:1440,height:1000});await page.getByRole('button',{name:'All people',exact:true}).click();
 await page.getByRole('button',{name:'Review by person',exact:true}).click();await page.getByRole('checkbox',{name:'Only people with suggestions',exact:true}).uncheck();
 await page.getByRole('button',{name:'Review suggestions for Maya',exact:true}).click();await page.getByRole('button',{name:'Choose portrait',exact:true}).click();
 await dialog.getByRole('button',{name:'Choose portrait 2: image-001.jpg',exact:true}).click();await dialog.getByRole('button',{name:'Save portrait',exact:true}).click();await dialog.waitFor({state:'hidden'});
 assert((await page.locator('.person-review-identity img').getAttribute('src')).includes('f001'));
 await page.locator('.sidebar nav').getByRole('button',{name:'Library tools',exact:true}).click();await page.getByRole('button',{name:'People names',exact:true}).click();
 await page.getByRole('checkbox',{name:'Show all saved names',exact:true}).check();
 const record=page.locator('.name-record').filter({hasText:'Maya'});assert((await record.locator('img').getAttribute('src')).includes('f001'));
 await record.getByRole('button',{name:'Choose portrait',exact:true}).click();await dialog.getByRole('button',{name:'Cancel',exact:true}).click();assert.equal(selected,'f001');
 failLoad=true;await record.getByRole('button',{name:'Choose portrait',exact:true}).click();await dialog.getByRole('alert').filter({hasText:'Fixture storage unavailable'}).waitFor();
 assert(await dialog.getByRole('button',{name:'Save portrait',exact:true}).isDisabled());failLoad=false;
 await dialog.getByRole('button',{name:'Refresh choices',exact:true}).click();await dialog.getByRole('button',{name:'Choose portrait 2: image-001.jpg',exact:true}).waitFor();await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
 assert(pages.includes(0)&&pages.includes(30)&&pages.includes(90));assert(writes.every(r=>r.name==='/api/people/1/portrait'));assert.deepEqual(errors,[]);
 console.log('Person portraits: exact saved face, all candidate pages, global persisted covers, People/review/name-tool entry points, automatic reset, cancellation, focus trap/Escape, stale and unavailable recovery, unavailable crops and mobile fit passed; no face assignments');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
