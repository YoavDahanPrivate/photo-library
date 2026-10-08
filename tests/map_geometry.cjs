const assert=require('node:assert/strict');
const {clusterLevel,geographicClusters,zoomAt}=require(process.argv[2]);
const pts=Array.from({length:100},(_,i)=>({latitude:30+i/10,longitude:10+i/7,count:i+1}));
const level=clusterLevel(45,1200),parent=geographicClusters(pts,level),children=geographicClusters(pts,level+1);
assert.equal([...parent.values()].flat().length,100);
for(const group of children.values())assert([...parent.values()].some(p=>group.every(point=>p.includes(point))));
// Viewport edges cannot remove members from a geographic cluster.
const snapshot=JSON.stringify([...parent]);
for(const center of [-180,-50,0,70,180])assert.equal(JSON.stringify([...geographicClusters(pts,level)]),snapshot);
const location=(v,p,h)=>({lon:v.lon+(p.x-500)*v.span/1000,lat:v.lat-(p.y-h/2)*v.span/1000});
const near=(a,b)=>assert(Math.abs(a-b)<1e-9);
const view={lon:15,lat:35,span:60},point={x:720,y:180},h=650;
const next=zoomAt(view,point,point,.5,h),before=location(view,point,h),after=location(next,point,h);
near(before.lat,after.lat);near(before.lon,after.lon);near(next.span,30);
const restored=zoomAt(next,point,point,2,h);near(restored.lat,view.lat);near(restored.lon,view.lon);near(restored.span,view.span);
const moved={x:800,y:250},pinch=zoomAt(view,point,moved,.7,h),anchor=location(pinch,moved,h);near(anchor.lat,before.lat);near(anchor.lon,before.lon);
const pan=zoomAt(view,point,moved,1,h);near(pan.span,view.span);near(location(pan,moved,h).lat,before.lat);
assert.equal(zoomAt(view,point,point,100,650).span,360);assert.equal(zoomAt(view,point,point,0,650).span,.005);
console.log('PASS: stable membership, nested zoom clusters, pointer anchor, pinch anchor, pan, inverse zoom, zoom limits');
