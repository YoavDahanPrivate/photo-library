const {chromium}=require(process.argv[2]||'playwright');
const fs=require('fs'),path=require('path');
(async()=>{
 const root=path.join(__dirname,'../frontend'),brand=path.join(root,'public/brand');
 const css=fs.readFileSync(path.join(root,'src/style.css'),'utf8');
 const gradient=css.match(/\.photo-brand-mark\{background:([^;]+);/)[1];
 const mask='data:image/png;base64,'+fs.readFileSync(path.join(brand,'dahan-photo-mark-v2.png')).toString('base64');
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({deviceScaleFactor:1});
  await page.setContent(`<style>html,body{margin:0;background:#f7f8f4}#mark{width:100vw;height:100vh;background:${gradient};mask:url('${mask}') center/contain no-repeat;-webkit-mask:url('${mask}') center/contain no-repeat}</style><div id="mark"></div>`);
  await page.evaluate(async src=>{const image=new Image();image.src=src;await image.decode();},mask);
  for(const size of [180,192,512]){
   await page.setViewportSize({width:size,height:size});
   const file=path.join(brand,`dahan-rainbow-v3-${size}.png`);await page.screenshot({path:file});
   console.log('Rendered',path.basename(file));
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
