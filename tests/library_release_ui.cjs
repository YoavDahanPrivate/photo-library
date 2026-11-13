const {chromium}=require(process.argv[2]||process.env.PLAYWRIGHT_MODULE||'playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const artifactDir=fs.mkdtempSync(path.join(require('os').tmpdir(),'dahan-ui-'));const root=path.join(__dirname,'../frontend/dist');
const server=http.createServer((req,res)=>{const file=path.join(root,new URL(req.url,'http://local').pathname==='/'?'index.html':new URL(req.url,'http://local').pathname);try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({channel:'msedge',headless:true});try{
for(const viewport of [{width:1440,height:900},{width:1920,height:1080},{width:390,height:844}]){
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
 await page.getByRole('button',{name:'Search library'}).click();await page.getByRole('combobox',{name:'Search photos'}).fill('holiday');await page.locator('#library-search-tools').getByRole('button',{name:'Search',exact:true}).click();await page.locator('#library-search-tools').waitFor({state:'hidden',timeout:10000});assert.equal(await page.locator('.library-active-search').count(),0);await page.getByRole('button',{name:'Search library'}).click();await page.getByRole('combobox',{name:'Search photos'}).fill('summer');await page.getByRole('combobox',{name:'Search photos'}).press('Enter');await page.locator('#library-search-tools').waitFor({state:'hidden',timeout:10000});await page.clock.runFor(50);assert(await page.locator('.unified-gallery-scroll').evaluate(e=>e===document.activeElement));await page.getByRole('button',{name:'Search library'}).click();await page.getByRole('button',{name:'Clear search',exact:true}).first().click();
 assert.equal(await page.locator('.library-source-picker summary').innerText(),'Fixture','Clearing search must preserve selected source');
 await page.getByRole('button',{name:'Close search',exact:true}).click();
 assert.equal(await page.locator('.metadata-tools').count(),0);await page.getByLabel('Appearance',{exact:true}).click();await page.getByRole('button',{name:'Select photos & videos',exact:true}).click();assert(await page.getByRole('button',{name:'Edit dates & locations',exact:true}).isVisible());
 await page.locator('.media-selection input').first().check();
 await page.getByRole('button',{name:'Share / save selected',exact:true}).click();await page.getByRole('dialog',{name:'Share and save selection',exact:true}).waitFor();
 await page.getByRole('button',{name:'Prepare selected files',exact:true}).click();await page.getByRole('button',{name:'Share / Save to Photos',exact:true}).waitFor();
 await page.waitForFunction(()=>!Array.from(document.querySelectorAll('button')).find(e=>e.textContent==='Share / Save to Photos')?.disabled);
 await page.getByRole('button',{name:'Share / Save to Photos',exact:true}).click();assert.equal(await page.evaluate(()=>window.__sharedNames.length),1);
 await page.getByText('Individual downloads & image saves',{exact:true}).click();assert((await page.getByRole('link',{name:'Download image 1',exact:true}).getAttribute('href')).includes('thumbnail?size=large'));
 await page.getByRole('combobox',{name:'Selection file format',exact:true}).selectOption('original');assert((await page.getByRole('link',{name:'Download original 1',exact:true}).getAttribute('href')).includes('original?download=true'));
 await page.screenshot({path:path.join(artifactDir,'selection-save-'+viewport.width+'.png')});
 await page.getByRole('button',{name:'Close selection save options',exact:true}).click();assert.equal(await page.getByRole('dialog',{name:'Share and save selection'}).count(),0);
 await page.screenshot({path:path.join(artifactDir,'selection-glass-'+viewport.width+'.png')});
 console.log('PASS',viewport.width,'selected JPEG share preparation, native share invocation, original/preview download URLs and explicit dialog close');
await page.getByRole('button',{name:'Cancel selection',exact:true}).click();
 if(viewport.width<=760)await page.getByRole('button',{name:'View options',exact:true}).click();
 await page.getByRole('combobox',{name:'Timeline grouping',includeHidden:true}).selectOption('days');await page.reload();await page.locator('.media-tile').first().waitFor();assert.equal(await page.getByRole('combobox',{name:'Timeline grouping',includeHidden:true}).inputValue(),'days');
 await page.clock.runFor(21000);await page.screenshot({path:path.join(artifactDir,`library-home-${viewport.width}.png`)});
 await page.evaluate(()=>{document.querySelector('main.library-workspace-page').scrollTop=800;});await page.clock.runFor(100);
 const header=await page.locator('.library-topbar').boundingBox();assert(Math.abs(header.y)<2,'Header must stay pinned');assert(await page.locator('.gallery-controls').evaluate(e=>e.closest('.library-topbar')&&e.getBoundingClientRect().top>=0),'Controls remain in fixed header');
 assert(await page.getByRole('button',{name:'Search library'}).isVisible());await page.screenshot({path:path.join(artifactDir,`library-home-scrolled-${viewport.width}.png`)});
 await page.getByRole('button',{name:'Search library'}).click();await page.clock.runFor(40);assert(await page.getByRole('combobox',{name:'Search photos'}).evaluate(e=>e===document.activeElement));
 await page.evaluate(()=>{const el=document.querySelector('main.library-workspace-page');el.scrollTop=el.scrollHeight;el.dispatchEvent(new Event('scroll'));});await page.clock.runFor(200);await page.waitForFunction(()=>document.querySelectorAll('.media-tile').length>80);assert(offsetSeen>=80);
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No horizontal overflow');

 if(viewport.width<=760){
 const card=page.locator('.media-tile').first();const icon=await card.locator('.tile-info-toggle').boundingBox();assert(icon.width<=24&&icon.height<=24,'Compact info icon');const outer=await card.boundingBox(),photo=await card.locator('.photo-card').boundingBox();assert(Math.abs(outer.height-photo.height)<2,'No mobile caption row');
 await card.locator('.tile-info-toggle').tap();assert(await card.locator('.tile-info-details').isVisible());assert.equal(await page.locator('.viewer-overlay').count(),0);await card.locator('.tile-info-toggle').tap();
 await page.screenshot({path:path.join(artifactDir,'compact-mobile-thumbnails.png')});
 await card.locator('.photo-card').tap();
 }else await page.locator('.photo-card').first().click();
 await page.locator('.viewer-overlay').waitFor({timeout:1500});assert(await page.locator('.viewer').isVisible(),'One activation opens before detail response');
 assert.equal(await page.getByText('Loading image…',{exact:true}).count(),0,'Metadata and neighbor requests must not show blocking image loading');
 await page.getByRole('button',{name:'Zoom in',exact:true}).click();assert.equal(await page.getByLabel('Zoom level',{exact:true}).innerText(),'150%');await page.getByRole('button',{name:'Fit to view',exact:true}).click();
 const pendingName=await page.locator('.viewer .incoming-frame img').getAttribute('alt');await page.getByRole('button',{name:'Next image or video',exact:true}).click();assert.notEqual(await page.locator('.viewer .incoming-frame img').getAttribute('alt'),pendingName,'Navigation works while all background endpoints are held');
 await page.getByRole('button',{name:'Close viewer',exact:true}).last().click();assert.equal(await page.locator('.viewer-overlay').count(),0);releaseDetail();releaseNeighbors();
 await page.clock.runFor(100);assert.equal(await page.locator('.viewer-overlay').count(),0,'Stale completions must not reopen preview');
 if(viewport.width<=760)await page.locator('.photo-card').first().tap();else await page.locator('.photo-card').first().click();
 console.log('PASS',viewport.width,'zoom, next and close while metadata/neighbors are held; stale responses do not reopen viewer');
 console.log('PASS',viewport.width,'single click/tap opens immediately while metadata is delayed');

 await page.locator('.viewer .incoming-frame img').waitFor();
 await page.waitForFunction(()=>document.querySelector('.viewer .incoming-frame img')?.getAttribute('src').includes('size=large'));
 assert(imageRequests.filter(u=>u.includes('size=large')).length>=2,'Nearby large previews should preload');
 assert.equal(imageRequests.filter(u=>u.includes('/display-original')).length,0,'Normal viewing should use preview');
 if(viewport.width<=760){
 assert.equal(await page.locator('.library-topbar').isVisible(),false);
 const mediaBox=await page.locator('.viewer-media').boundingBox();assert(mediaBox.height>viewport.height*.85,'Preview should fill mobile screen');
 assert.equal(await page.locator('.media-info-content').isVisible(),false);
 await page.screenshot({path:path.join(artifactDir,'mobile-preview.png')});
 let grip=await page.locator('.media-info-handle').boundingBox();
 await page.mouse.move(grip.x+grip.width/2,grip.y+28);await page.mouse.down();await page.mouse.move(grip.x+grip.width/2,grip.y-240,{steps:12});await page.mouse.up();
 assert.equal(await page.locator('.media-info-handle').getAttribute('aria-expanded'),'true');assert(await page.locator('.media-info-content').isVisible());
 await page.screenshot({path:path.join(artifactDir,'mobile-information-sheet.png')});
 const themeColors=[];
 for(const theme of ['sage','ocean','plum','black','dark']){
 await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
 const colors=await page.locator('.media-info-sheet').evaluate(el=>{
  const ctx=document.createElement('canvas').getContext('2d');
  const rgb=c=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=c;ctx.fillRect(0,0,1,1);return Array.from(ctx.getImageData(0,0,1,1).data).slice(0,3);};
  const lum=c=>rgb(c).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
  const style=getComputedStyle(el),bg=style.backgroundColor,txt=getComputedStyle(el.querySelector('dd')).color,muted=getComputedStyle(el.querySelector('dt')).color;
  const ratio=(a,b)=>(Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);
  return {background:bg,brightness:lum(bg),textContrast:ratio(txt,bg),labelContrast:ratio(muted,bg)};
 });
 assert(colors.brightness<.06,'Sheet must remain dark in '+theme);assert(colors.textContrast>=4.5&&colors.labelContrast>=4.5,'Readable sheet text in '+theme);
 themeColors.push(colors.background);
 await page.screenshot({path:path.join(artifactDir,'sheet-tone-'+theme+'.png')});
 await page.getByRole('button',{name:'Hide photo information',exact:true}).click();
 await page.screenshot({path:path.join(artifactDir,'sheet-handle-'+theme+'.png')});
 await page.getByRole('button',{name:'Show photo information',exact:true}).click();
 }
 assert(new Set(themeColors).size===5,'Theme tint must follow each selected palette');
 await page.evaluate(()=>document.documentElement.dataset.theme='sage');
 console.log('PASS sheet tone and text contrast across sage, ocean, plum, black and dark');
 for(const landscapeWidth of [844,932,1024]){
 await page.setViewportSize({width:landscapeWidth,height:390});await page.clock.runFor(100);
 assert.equal(await page.locator('.media-info-handle').getAttribute('aria-expanded'),'true');
 const sheetBox=await page.locator('.media-info-sheet').boundingBox();assert(Math.abs(sheetBox.width-landscapeWidth)<2&&sheetBox.height<391,'Landscape information stays bottom sheet');
 assert.equal(await page.locator('.media-info-content dl').evaluate(e=>getComputedStyle(e).display),'grid');
 const facts=await page.locator('.media-info-content dl').evaluate(e=>{const nodes=Array.from(e.children).slice(0,4).map(x=>x.getBoundingClientRect());return {y:nodes.map(r=>r.y),x:nodes.map(r=>r.x),overflow:e.scrollWidth>e.clientWidth};});
 assert(Math.max(...facts.y)-Math.min(...facts.y)<8,'Two label/value pairs share a row');assert(facts.x[2]>facts.x[1],'Second fact appears alongside first');assert(!facts.overflow,'No horizontal overflow');
 await page.locator('.media-info-content dd').first().evaluate(e=>e.textContent='VeryLongSourceNameWithoutSpaces'.repeat(8));assert(await page.locator('.media-info-content').evaluate(e=>e.scrollWidth<=e.clientWidth),'Long values wrap');

 assert(await page.locator('.media-info-handle').isVisible());assert.equal(await page.locator('.library-topbar').isVisible(),false);
 const scrolled=await page.locator('.media-info-content').evaluate(e=>{e.scrollTop=100;return e.scrollTop});assert(scrolled>0,'Landscape sheet content scrolls');
 await page.screenshot({path:path.join(artifactDir,'landscape-facts-'+landscapeWidth+'.png')});
 let h=await page.locator('.media-info-handle').boundingBox();await page.mouse.move(h.x+h.width/2,h.y+28);await page.mouse.down();await page.mouse.move(h.x+h.width/2,h.y+160,{steps:10});await page.mouse.up();assert.equal(await page.locator('.media-info-handle').getAttribute('aria-expanded'),'false');
 await page.setViewportSize({width:390,height:844});await page.clock.runFor(100);assert.equal(await page.locator('.media-info-handle').getAttribute('aria-expanded'),'false');
 await page.setViewportSize({width:landscapeWidth,height:390});await page.clock.runFor(100);await page.getByRole('button',{name:'Show photo information',exact:true}).tap();assert(await page.locator('.media-info-content').isVisible());
 await page.setViewportSize({width:390,height:844});await page.clock.runFor(100);assert.equal(await page.locator('.media-info-handle').getAttribute('aria-expanded'),'true');assert.equal(await page.locator('.media-info-content dl').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length),2,'Narrow sheets use one label/value pair at a time');
 }
 console.log('PASS touch portrait/landscape rotations, retained open/closed state, landscape drag, tap and scrolling at 844/932/1024');


 grip=await page.locator('.media-info-handle').boundingBox();await page.mouse.move(grip.x+grip.width/2,grip.y+28);await page.mouse.down();await page.mouse.move(grip.x+grip.width/2,grip.y+240,{steps:12});await page.mouse.up();
 assert.equal(await page.locator('.media-info-handle').getAttribute('aria-expanded'),'false');
 await page.getByRole('button',{name:'Show photo information',exact:true}).click();assert(await page.locator('.media-info-content').isVisible());
 await page.getByRole('button',{name:'Hide photo information',exact:true}).press('Escape');assert.equal(await page.locator('.media-info-content').isVisible(),false);
 console.log('PASS mobile full-screen preview, hidden header, drag up/down, tap and keyboard sheet dismissal');
 }

 if(viewport.width>760){
 assert.equal(await page.locator('.library-topbar').isVisible(),false);
 const box=await page.locator('.viewer').boundingBox();assert(box.width>=viewport.width*.95&&box.height>=viewport.height*.95,'Desktop preview must fill most of window');
 assert(await page.locator('.viewer-info').isVisible(),'Desktop information remains accessible');
 await page.screenshot({path:path.join(artifactDir,'desktop-preview-'+viewport.width+'.png')});
 console.log('PASS',viewport.width,'hidden Library header, large desktop preview and accessible information');
 }
 if(viewport.width<=760)await page.locator('.media-viewport').tap();
 const firstImage=await page.locator('.viewer .incoming-frame img').getAttribute('alt');
 await page.getByRole('button',{name:'Next image or video',exact:true}).click();
 await page.waitForFunction(name=>document.querySelector('.viewer .incoming-frame img')?.getAttribute('alt')!==name,firstImage);
 await page.getByRole('button',{name:'Expand to fullscreen',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.viewer .incoming-frame img')?.getAttribute('src').includes('/display-original'));
 assert(imageRequests.some(u=>u.includes('/display-original')),'Fullscreen should load original resolution');
 await page.getByRole('button',{name:'Zoom in',exact:true}).click();
 assert.equal(await page.getByLabel('Zoom level',{exact:true}).innerText(),'150%');
 await page.getByRole('button',{name:'Collapse fullscreen view',exact:true}).click();
 await page.getByRole('button',{name:'Close viewer',exact:true}).last().click();
 assert.equal(await page.locator('.viewer-overlay').count(),0);assert(await page.locator('.library-topbar').isVisible(),'Library header returns after preview closes');
 await page.getByLabel('Appearance',{exact:true}).click();await page.locator('.library-topbar h1').click();assert.equal(await page.locator('.library-appearance').getAttribute('open'),null);
 await page.getByLabel('Appearance',{exact:true}).click();await page.getByRole('button',{name:'Close menu',exact:true}).click();assert.equal(await page.locator('.library-appearance').getAttribute('open'),null);
 await page.getByLabel('Appearance',{exact:true}).click();await page.keyboard.press('Escape');assert.equal(await page.locator('.library-appearance').getAttribute('open'),null);
 await page.getByLabel('Appearance',{exact:true}).click();await page.getByRole('button',{name:'Select photos & videos',exact:true}).click();await page.keyboard.press('Escape');assert.equal(await page.locator('.metadata-tools').count(),0);assert.equal(await page.locator('.media-selection').count(),0);
 console.log('PASS',viewport.width,'outside tap, Close and Escape dismiss menu; Escape cancels selection');

 console.log('PASS',viewport.width,'viewer previews, prefetch, navigation, original-resolution fullscreen, zoom, close');
 assert.deepEqual(errors,[]);console.log('PASS',viewport.width,'collapsed mobile options, source selection, search click/Enter collapse, gallery focus, preferences and pagination');
 await page.route('**/version.json*',r=>r.fulfill({json:{version:'11111111-1111-4111-8111-111111111111'}}));await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
 await page.locator('.app-update-notice').waitFor();
 const fit=await page.locator('.app-update-notice').evaluate(e=>{const r=e.getBoundingClientRect(),b=e.querySelector('button').getBoundingClientRect();return {gap:r.right-b.right,width:r.width}});assert(fit.gap<=16,'Update notice should have only padding after button');assert(fit.width<=viewport.width-24);
 await page.screenshot({path:path.join(artifactDir,'update-notice-'+viewport.width+'.png')});console.log('PASS',viewport.width,'content-sized update notice');await page.close();
}
}finally{await browser.close();server.close();}})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
