const {chromium}=require(process.argv[2]);
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const root=path.join(__dirname,'../frontend/dist');
const server=http.createServer((req,res)=>{
  const pathname=new URL(req.url,'http://local').pathname;
  const file=path.join(root,pathname==='/'?'index.html':pathname);
  try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}
  catch{res.writeHead(404).end();}
});
(async()=>{
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    for(const viewport of [{width:1440,height:900},{width:390,height:844}]){
      const page=await browser.newPage({viewport,isMobile:viewport.width<500,hasTouch:viewport.width<500});
      const errors=[];page.on('pageerror',e=>errors.push(e.message));let historyRequests=0,mapRequests=0,stallMedia=false;
      let releaseMedia;const mediaGate=new Promise(resolve=>releaseMedia=resolve);
      await page.route('**/api/**',async route=>{
        const p=new URL(route.request().url()).pathname;let json=[];
        if(p==='/api/auth/me')json={id:'qa',name:'QA',theme:'light',source_ids:null,source_names:null};
        else if(p==='/api/status')json={revision:1,total:1,counts:{ready:1},features:{}};
        else if(p==='/api/sync/status')json={running:false,runs:[]};
        else if(p==='/api/library/hierarchy')json={databases:[],sources:[],linked_sources:[]};
        else if(p==='/api/sources')json=[{phone:'Fixture',album:'Album',count:1}];
        else if(p==='/api/search/validate')json={valid:true};
        else if(p==='/api/media'){if(stallMedia)await mediaGate;json={total:1,items:[{id:'m0',name:'Photo',phone:'Fixture',album:'Album',kind:'photo',taken:'2020-01-01',width:800,height:600,people_names:[]}]};}
        else if(p==='/api/metadata/history'){historyRequests++;json=[];}
        else if(p==='/api/people/operations/current')json=null;
        else if(p==='/api/place-options')json={options:[]};
        else if(p==='/api/map/countries'||p==='/api/map/land')json={type:'FeatureCollection',features:[]};
        else if(p.includes('/thumbnail'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#abc"/></svg>'});
        else if(p==='/api/map-results'||p==='/api/map-context'){mapRequests++;json={points:[],known:0,unlocated:1,place_only:0,no_gps:1,total:1};}
        await route.fulfill({json});
      });
      await page.goto('http://127.0.0.1:'+server.address().port);
      await page.locator('.media-tile').first().waitFor();
      assert.equal(historyRequests,0,'Initial gallery must not request history');
      assert.equal(mapRequests,0,'Closed map must not query the catalogue');
      await page.getByLabel('Appearance',{exact:true}).click();
      await page.getByRole('button',{name:'Select photos & videos',exact:true}).click();
      await page.waitForResponse(r=>r.url().includes('/api/metadata/history'));
      assert.equal(historyRequests,1,'Entering selection loads history once');
      await page.getByRole('button',{name:'Cancel selection',exact:true}).first().click();
      assert.equal(historyRequests,1,'Leaving selection must not reload history');
      await page.getByRole('button',{name:'Search library',exact:true}).click();
      const mapResponse=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/map-results');
      await page.getByRole('button',{name:'Map',exact:true}).click();await mapResponse;
      assert.equal(mapRequests,2,'Opening the map loads matching and context results');
      await page.getByRole('button',{name:'Close search helper',exact:true}).click();
      await page.clock.install();stallMedia=true;
      const pending=page.waitForRequest(r=>new URL(r.url()).pathname==='/api/media');
      await page.reload();await page.clock.runFor(500);await pending;
      await page.clock.runFor(31000);
      await page.getByRole('button',{name:'Retry loading results',exact:true}).waitFor();
      await page.getByRole('heading',{name:'Results could not be loaded',exact:true}).waitFor();
      assert.equal(await page.getByRole('heading',{name:'No moments in this view',exact:true}).count(),0);
      await page.locator('.results-loading-banner').waitFor({state:'hidden'});
      stallMedia=false;releaseMedia();
      await page.getByRole('button',{name:'Retry loading results',exact:true}).click();
      await page.clock.runFor(500);
      await page.locator('.media-tile').first().waitFor();
      await page.locator('.results-loading-banner').waitFor({state:'hidden'});
      assert.deepEqual(errors,[]);
      console.log('PASS',viewport.width,'gallery skips history/maps; selection loads history; stalled request times out and retry recovers');
      await page.close();
    }
  }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exit(1)});
