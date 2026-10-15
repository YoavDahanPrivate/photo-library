const {chromium}=require(process.argv[2]||'playwright');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../frontend/dist'),output=process.env.DAHAN_QA_OUTPUT||require('os').tmpdir();fs.mkdirSync(output,{recursive:true});
const server=http.createServer((req,res)=>{const name=new URL(req.url,'http://localhost').pathname,file=path.resolve(root,'.'+(name==='/'?'/index.html':name));if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],writes=[];page.on('pageerror',error=>errors.push(error.stack));
 let people=[{id:1,name:'Zoe',count:9,cover:'a'},{id:2,name:'Alice',count:3,cover:'b'},{id:3,name:'Bob',count:100,cover:'c'},{id:6,name:'alice',count:3,cover:'d'},{id:4,name:null,count:50,cover:'e'},{id:5,name:'   ',count:20,cover:'f'},{id:-1,name:'Unknown People',count:70,cover:'g'},{id:0,name:'Unassigned faces',count:5,cover:'h'},...Array.from({length:130},(_,i)=>({id:i+100,name:null,count:2,cover:'i'}))];
 await page.route('**/api/**',async route=>{
  const req=route.request(),name=new URL(req.url()).pathname;let value=[];if(req.method()!=='GET'){writes.push(name);await route.abort();return;}
  if(name==='/api/people')value=people;
  else if(name==='/api/people/calibration')value={report:null,active_id:null,effective_mode:'conservative'};
  else if(name==='/api/people/operations/current')value=null;
  else if(name==='/api/status')value={revision:0,total:1,counts:{ready:1},faces:300,features:{}};
  else if(name==='/api/sync/status')value={running:false,runs:[]};
  else if(name==='/api/library/hierarchy')value={databases:[],sources:[],linked_sources:[]};
  else if(name==='/api/sources')value=[{phone:'Fixture',album:'Album',count:1}];
  else if(name==='/api/media')value={items:[],total:0};
  else if(name==='/api/place-options')value={options:[]};
  else if(name.includes('thumbnail')){await route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><rect width="120" height="120" fill="#e8eee0"/><ellipse cx="60" cy="48" rx="25" ry="30" fill="#afc5a6"/><path d="M15 120 Q15 78 60 78 Q105 78 105 120" fill="#7c9b73"/></svg>'});return;}
  await route.fulfill({json:value});
 });
 const visit=async()=>{await page.goto('http://127.0.0.1:'+server.address().port+'/');await page.locator('.sidebar nav').getByRole('button',{name:/^People/}).click();await page.locator('.people-grid .person-card').first().waitFor();};
 await visit();const options=page.getByRole('region',{name:'People display options'}),known=options.getByRole('button',{name:'Known people',exact:true}),unknown=options.getByRole('button',{name:'Unknown people',exact:true}),sort=options.getByRole('combobox',{name:'Sort people by'}),ascending=options.getByRole('button',{name:'Ascending people order'}),descending=options.getByRole('button',{name:'Descending people order'});
 const ids=()=>page.locator('.people-grid [data-person-card]').evaluateAll(rows=>rows.map(row=>Number(row.dataset.personCard)));
 assert.equal(await known.getAttribute('aria-pressed'),'true');assert.equal(await unknown.getAttribute('aria-pressed'),'true');assert.equal(await sort.inputValue(),'name');assert.equal(await ascending.getAttribute('aria-pressed'),'true');
 await unknown.click();assert.deepEqual(await ids(),[2,6,3,1]);assert.equal(await page.getByRole('region',{name:'Select unnamed groups'}).count(),0);assert(await known.isDisabled());
 await descending.click();assert.deepEqual(await ids(),[1,3,2,6]);await sort.selectOption('count');assert.equal(await descending.getAttribute('aria-pressed'),'true');assert.deepEqual(await ids(),[3,1,2,6]);await ascending.click();assert.deepEqual(await ids(),[2,6,1,3]);
 await sort.selectOption('name');assert.equal(await descending.getAttribute('aria-pressed'),'true');await sort.selectOption('count');assert.equal(await ascending.getAttribute('aria-pressed'),'true');
 await visit();assert.equal(await unknown.getAttribute('aria-pressed'),'false');assert.equal(await sort.inputValue(),'count');assert.equal(await ascending.getAttribute('aria-pressed'),'true');assert.deepEqual(await ids(),[2,6,1,3]);
 await page.locator('[data-person-card="3"] .person-card').click();await page.getByRole('button',{name:'All people',exact:true}).click();assert.deepEqual(await ids(),[2,6,1,3]);
 await options.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'people-browse-desktop.png')});
 await unknown.click();await known.click();assert.equal(await known.getAttribute('aria-pressed'),'false');assert(await unknown.isDisabled());
 await page.locator('.load-more').scrollIntoViewIfNeeded();await page.waitForFunction(()=>document.querySelectorAll('.people-grid [data-person-card]').length===134);const unseen=await ids();assert(unseen.includes(-1)&&unseen.includes(0)&&unseen.includes(5)&&unseen.includes(229));assert(unseen.every(id=>![1,2,3,6].includes(id)));assert.equal(new Set(unseen).size,134);
 await page.getByRole('checkbox',{name:'Select unnamed person 100',exact:true}).check();await known.click();await unknown.click();assert.equal(await page.getByRole('region',{name:'Select unnamed groups'}).count(),0);await unknown.click();await page.getByText('0 of 132 unnamed groups selected',{exact:false}).waitFor();await unknown.click();
 await page.setViewportSize({width:390,height:844});await options.scrollIntoViewIfNeeded();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(output,'people-browse-mobile.png')});
 // Persisted preference corruption and an accidental empty filter recover to usable defaults.
 await page.evaluate(()=>localStorage.setItem('dahan.peopleBrowse.v1','broken json'));await page.setViewportSize({width:1440,height:1000});await visit();assert.equal(await sort.inputValue(),'name');assert.equal(await ascending.getAttribute('aria-pressed'),'true');assert.equal(await known.getAttribute('aria-pressed'),'true');assert.equal(await unknown.getAttribute('aria-pressed'),'true');
 await page.evaluate(()=>localStorage.setItem('dahan.peopleBrowse.v1',JSON.stringify({known:false,unknown:false,sort:'nonsense',directions:{name:'bad',count:0}})));await visit();assert.equal(await known.getAttribute('aria-pressed'),'true');assert.equal(await unknown.getAttribute('aria-pressed'),'true');assert.equal(await sort.inputValue(),'name');
 people=people.filter(row=>row.id<=0||!row.name?.trim());await unknown.click();await page.reload();await page.locator('.sidebar nav').getByRole('button',{name:/^People/}).click();await page.getByText('No named people yet.',{exact:false}).waitFor();assert.equal(await ids().then(rows=>rows.length),0);await unknown.click();await page.locator('.people-grid .person-card').first().waitFor();
 assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);console.log('People directory: known/unknown/all including special buckets, case-insensitive names, stable count ties, both sort directions/defaults, per-sort persistence/reload/return, full filtered lazy loading, hidden-selection clearing, malformed preferences, empty results and mobile passed; no API writes');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
