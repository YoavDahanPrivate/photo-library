const {chromium}=require(process.argv[2]||'playwright');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../frontend/dist'),output=process.env.DAHAN_QA_OUTPUT||require('os').tmpdir();
fs.mkdirSync(output,{recursive:true});
const server=http.createServer((req,res)=>{const name=new URL(req.url,'http://localhost').pathname,file=path.resolve(root,'.'+(name==='/'?'/index.html':name));if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],writes=[];
 page.on('pageerror',error=>{errors.push(error.stack);console.error(error.stack);});
 const settings={frequency:'off',time:'03:00',weekday:0,month_day:1,timezone:'UTC',auto_assign:false};
 const database={id:'fixture',root:'C:\\Fixture photos',alias:'Fixture photos',layout:'collection',exclusions:[],visible:true,sync_enabled:true,availability:'available',last_error:null,media_count:60,sources:[],schedule:null,next_due:null};
 let runs=[],running=false,fail=false;
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),name=url.pathname;let value=[];
  if(req.method()!=='GET'){
   writes.push(name+url.search);
   if(fail){await route.fulfill({status:409,json:{detail:'Fixture scan is busy'}});return;}
   if(name.endsWith('/resume')){running=true;runs=runs.map(r=>({...r,state:'running'}));}
   else if(name.endsWith('/pause')){running=false;runs=runs.map(r=>({...r,state:'paused'}));}
   else {running=true;runs=[{id:'run-1',state:'running',started:'2026-10-19T08:00:00Z',finished:null,reason:'manual',error:null,progress:{database_id:name.includes('/databases/')?'fixture':undefined,sync_mode:url.searchParams.get('mode'),checkpoint_version:2,phase:'Reading source folders',folders_checked:20,folders_reused:17,folders_read:3,file_metadata_reused:1200,media_found:1240}}];}
   value={id:'run-1',state:'running'};
  } else if(name==='/api/sync/status')value={settings,next_due:null,running,runs};
  else if(name==='/api/duplicates/status')value={jobs:[],reviews:[],trash_count:0};
  else if(name==='/api/databases')value=[database];
  else if(name==='/api/databases/folders/capabilities')value={available:false,reason:'Fixture'};
  else if(name==='/api/sync/assignments')value={actions:[],faces:[]};
  else if(name==='/api/people/operations/current')value=null;
  else if(name==='/api/status')value={revision:0,total:60,counts:{ready:60},faces:0,features:{}};
  else if(name==='/api/library/hierarchy')value={databases:[],sources:[],linked_sources:[]};
  else if(name==='/api/media')value={items:[],total:0};
  else if(name==='/api/place-options')value={options:[]};
  await route.fulfill({json:value});
 });
 let visits=0;
 const visit=async(section='databases')=>{await page.goto('http://127.0.0.1:'+server.address().port+'/?fixture='+ ++visits+'#tools/'+section);await page.getByRole('heading',{name:'Library tools',exact:true}).waitFor();};
 await visit();await page.getByRole('button',{name:'More',exact:true}).click();
 const manage=page.locator('.manager-detail-row').filter({has:page.getByRole('heading',{name:'Manage Fixture photos'})});
 await manage.getByRole('button',{name:'Sync',exact:true}).click();
 await page.getByRole('region',{name:'Fixture photos sync progress'}).getByText('Sync · Reading source folders',{exact:true}).waitFor();
 assert.equal(writes.at(-1),'/api/databases/fixture/sync?mode=sync');
 assert(await manage.getByRole('button',{name:'Sync',exact:true}).isDisabled());
 assert(await manage.getByRole('button',{name:'Full Sync',exact:true}).isDisabled());
 await page.getByText('17 folder listings reused · 3 folder listings refreshed · 1,200 cached file sizes/dates reused.',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Pause scan',exact:true}).click();await page.getByRole('button',{name:'Resume scan',exact:true}).waitFor();
 await page.getByRole('button',{name:'Resume scan',exact:true}).click();assert.equal(writes.at(-1),'/api/sync/runs/run-1/resume');
 running=false;runs=[];await visit();await page.getByRole('button',{name:'More',exact:true}).click();
 await manage.getByRole('button',{name:'Full Sync',exact:true}).click();assert.equal(writes.at(-1),'/api/databases/fixture/sync?mode=full');
 await page.getByRole('region',{name:'Fixture photos sync progress'}).getByText('Full Sync · Reading source folders',{exact:true}).waitFor();
 await page.screenshot({path:path.join(output,'sync-modes-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});await manage.getByRole('button',{name:'Full Sync',exact:true}).scrollIntoViewIfNeeded();
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:path.join(output,'sync-modes-mobile.png'),fullPage:true});
 running=false;runs=[];await visit('sync');
 const status=page.getByRole('region',{name:'Sync status',exact:true});
 await status.getByRole('button',{name:'Sync',exact:true}).click();assert.equal(writes.at(-1),'/api/sync/now?mode=sync');
 assert(await status.getByRole('button',{name:'Full Sync',exact:true}).isDisabled());
 await status.getByRole('button',{name:'Pause',exact:true}).click();await status.getByRole('button',{name:'Resume',exact:true}).click();
 assert.equal(writes.at(-1),'/api/sync/runs/run-1/resume');
 running=false;runs=[];await visit('sync');await status.getByRole('button',{name:'Full Sync',exact:true}).click();
 assert.equal(writes.at(-1),'/api/sync/now?mode=full');
 await status.getByText('Full Sync · Reading source folders',{exact:true}).waitFor();
 assert.equal(await page.getByText('This run started before file-check checkpoints were available.',{exact:false}).count(),0);
 running=false;runs=[];fail=true;await visit('sync');await status.getByRole('button',{name:'Sync',exact:true}).click();
 await page.getByRole('alert').filter({hasText:'Fixture scan is busy'}).waitFor();assert(await status.getByRole('button',{name:'Sync',exact:true}).isEnabled());
 fail=false;database.sync_enabled=false;await visit();await page.getByRole('button',{name:'More',exact:true}).click();
 assert(await manage.getByRole('button',{name:'Sync',exact:true}).isDisabled());assert(await manage.getByRole('button',{name:'Full Sync',exact:true}).isDisabled());
 assert.deepEqual(errors,[]);
 console.log('Sync / Full Sync: per-database and global requests, mode/progress/cache counts, safe pause/resume, concurrent/disabled guards, API errors, desktop/mobile passed against isolated API fixtures');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
