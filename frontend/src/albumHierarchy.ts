type AlbumLocationInput={album:string;albumKey?:string|null;relative?:string|null;sourceKey?:string|null;directory?:boolean};
const parts=(value:string)=>value.replace(/\\/g,'/').split('/').filter(part=>part!==''&&part!=='.');

/** Display folder hierarchy while keeping the underlying Album identity intact. */
export function albumLocation({album,albumKey,relative,sourceKey,directory=false}:AlbumLocationInput){
 const key=albumKey===undefined||albumKey===null?undefined:parts(albumKey);
 const labelParts=key??album.split(' › ');
 const parent=key?.length?album===key.join(' › ')?key[0]:album:key?album:labelParts[0];
 let folders=relative===undefined||relative===null?undefined:parts(relative);
 if(folders){
  if(!directory)folders=folders.slice(0,-1);
  const source=parts(sourceKey||'');
  if(source.length&&source.every((part,index)=>folders![index]===part))folders=folders.slice(source.length);
 }
 // A single/root Album keeps every descendant beneath its existing caption.
 // Otherwise the first directory is the Album and the rest is its subpath.
 const nested=key?folders?folders.slice(key.length?1:0):key.slice(1):labelParts.slice(1);
 return {album:parent,subAlbum:nested.join('/')};
}
