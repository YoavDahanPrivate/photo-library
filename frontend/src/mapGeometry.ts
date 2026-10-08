export type MapView = {lat:number;lon:number;span:number};
export type MapPoint = {latitude:number;longitude:number};
export function clusterLevel(span:number,width:number) {return Math.max(0,Math.floor(Math.log2(360/(span*72/Math.max(1,width)))));}
export function geographicClusters<T extends MapPoint>(points:T[],level:number) {
 const cell=360/2**level,groups=new Map<string,T[]>();
 for(const p of points){const key=level+":"+Math.floor((p.longitude+180)/cell)+":"+Math.floor((p.latitude+90)/cell);const group=groups.get(key);if(group)group.push(p);else groups.set(key,[p]);}
 return groups;
}
export function zoomAt(v:MapView,from:{x:number;y:number},to:{x:number;y:number},factor:number,height:number):MapView{
 const span=Math.max(.005,Math.min(360,v.span*factor));
 const lon=v.lon+(from.x-500)*v.span/1000;
 const lat=v.lat-(from.y-height/2)*v.span/1000;
 return {span,lon:Math.max(-180,Math.min(180,lon-(to.x-500)*span/1000)),lat:Math.max(-85,Math.min(85,lat+(to.y-height/2)*span/1000))};
}

// Fit a mouse-drawn box while preserving the viewport's aspect ratio.
export function zoomToRectangle(r:{south:number;north:number;west:number;east:number},height:number):MapView {
 return {lat:(r.south+r.north)/2,lon:(r.west+r.east)/2,span:Math.max(.005,Math.min(360,Math.max(r.east-r.west,(r.north-r.south)*1000/height)*1.08))};
}
export function countryAnchor(polygons:number[][][][],v:MapView,height:number,preferred:{lon:number;lat:number}) {
 const w=v.lon-v.span/2,e=v.lon+v.span/2,s=v.lat-v.span*height/2000,n=v.lat+v.span*height/2000;
 const inside=(p:number[],ring:number[][])=>{let yes=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){const a=ring[i],b=ring[j];if((a[1]>p[1])!==(b[1]>p[1]) && p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0])yes=!yes;}return yes;};
 const valid=(p:number[])=>polygons.some(poly=>inside(p,poly[0])&&!poly.slice(1).some(hole=>inside(p,hole)));
 if(preferred.lon>w && preferred.lon<e && preferred.lat>s && preferred.lat<n)return preferred;
 // Clip each outer polygon against the viewport, then choose a point inside it.
 // Sampling within the clipped bounds also handles small countries at a border.
 for(const poly of polygons){
  let ring=poly[0];
  for(const [axis,bound,sign] of [[0,w,1],[0,e,-1],[1,s,1],[1,n,-1]]){
   const out:number[][]=[];
   for(let i=0;i<ring.length;i++){const a=ring[i],b=ring[(i+1)%ring.length],ai=(a[axis]-bound)*sign>=0,bi=(b[axis]-bound)*sign>=0;if(ai)out.push(a);if(ai!==bi){const t=(bound-a[axis])/(b[axis]-a[axis]);out.push([a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])]);}}
   ring=out;if(!ring.length)break;
  }
  if(ring.length<3)continue;
  const xs=ring.map(p=>p[0]),ys=ring.map(p=>p[1]),left=Math.min(...xs),right=Math.max(...xs),bottom=Math.min(...ys),top=Math.max(...ys);
  const candidates:number[][]=[];
  for(const fx of [.5,.25,.75,.1,.9])for(const fy of [.5,.25,.75,.1,.9])candidates.push([left+(right-left)*fx,bottom+(top-bottom)*fy]);
  const point=candidates.find(p=>valid(p));if(point)return {lon:point[0],lat:point[1]};
 }
 return null;
}
