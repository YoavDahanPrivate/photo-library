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
  const browser=await chromium.launch({executablePath:process.env.TEST_CHROMIUM_PATH,headless:true});
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
        else if(p==='/api/map/labels')json={cities:[]};
        else if(p==='/api/place-options')json={options:[]};
        else if(p==='/api/map/countries'||p==='/api/map/land')json={type:'FeatureCollection',features:[]};
        else if(p.includes('/thumbnail'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#abc"/></svg>'});
        else if(p==='/api/map-results'||p==='/api/map-context'){mapRequests++;json={points:[{latitude:30,longitude:20,count:1,city:'Test city',country:'Test country'},{latitude:40,longitude:40,count:1,city:'Other city',country:'Test country'}],known:2,unlocated:0,place_only:0,no_gps:0,total:2};}
        await route.fulfill({json});
      });
      await page.goto('http://127.0.0.1:'+server.address().port);
      await page.locator('.media-tile').first().waitFor();

      await page.getByRole('button',{name:'Search library',exact:true}).click();
      await page.getByRole('button',{name:'Map',exact:true}).click();
      await page.getByRole('button',{name:'Add area',exact:true}).click();
      const map=page.locator('.interactive-map');await map.scrollIntoViewIfNeeded();const box=await map.boundingBox();
      const marker=await page.locator('.geo-marker').first().boundingBox();const x=marker.x+marker.width/2,y=marker.y+marker.height/2,dx=box.width*.15,dy=-box.height*.15;
      if(viewport.width<500){const cdp=await page.context().newCDPSession(page);await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});for(let i=1;i<=8;i++)await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+dx*i/8,y:y+dy*i/8}]});await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});}
      else{await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+dx,y+dy,{steps:8});await page.mouse.up();}

      await page.getByRole('button',{name:'Remove included area 1',exact:true}).waitFor({timeout:3000});

      await page.getByRole('button',{name:'Clear areas',exact:true}).click();
      const tapAt=async(x,y)=>{if(viewport.width<500)await page.touchscreen.tap(x,y);else await page.mouse.click(x,y);};
      for(const [tool,chip] of [['Add area','included'],['Exclude area','excluded']]){
        await page.getByRole('button',{name:tool,exact:true}).click();
        const b=await map.boundingBox();await tapAt(b.x+b.width*.3,b.y+b.height*.3);
        await page.getByRole('status',{name:'First area corner selected',exact:true}).waitFor();
        await tapAt(b.x+b.width*.65,b.y+b.height*.65);
        await page.getByRole('button',{name:'Remove '+chip+' area 1',exact:true}).waitFor();
        assert.equal(await page.locator('.map-area-start').count(),0);
      }
      await page.getByRole('button',{name:'Add area',exact:true}).click();
      let b=await map.boundingBox();await tapAt(b.x+b.width*.3,b.y+b.height*.3);
      await page.getByRole('button',{name:'Pan',exact:true}).click();assert.equal(await page.locator('.map-area-start').count(),0);
      if(viewport.width<500){
        await page.getByRole('button',{name:'Add area',exact:true}).click();
        const cdp=await page.context().newCDPSession(page);b=await map.boundingBox();
        const points=[{id:1,x:b.x+b.width*.3,y:b.y+b.height*.4},{id:2,x:b.x+b.width*.6,y:b.y+b.height*.6}];
        await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:points});
        await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:points.map((p,i)=>({...p,x:p.x+(i?15:-15)}))});
        await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
        assert.equal(await page.locator('.map-area-start').count(),0);assert.equal(await page.getByRole('button',{name:/Remove included area/}).count(),1);
      }
      const artifact=path.join(require('os').tmpdir(),'dahan-map-area-'+viewport.width+'.png');await page.screenshot({path:artifact});
      const applied=page.waitForRequest(r=>new URL(r.url()).pathname==='/api/media'&&new URL(r.url()).searchParams.get('expression')?.includes('Area('));
      await page.locator('.map-search-dialog').getByRole('button',{name:'Apply search',exact:true}).click();await applied;
      assert.deepEqual(errors,[]);console.log('PASS',viewport.width,'marker drag, two-corner include/exclude, mode reset, pinch safety, applied search. Screenshot:',artifact);

      await page.close();
    }
  }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exit(1)});
