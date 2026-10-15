import {albumLocation} from './albumHierarchy';

export default function AlbumLocation({album,albumKey,relative,sourceKey,directory=false}:{album:string;albumKey?:string;relative?:string;sourceKey?:string;directory?:boolean}){
 const location=albumLocation({album,albumKey,relative,sourceKey,directory});
 return <div className="album-location"><span className="album-location-parent">{location.album}</span>{location.subAlbum&&<small className="album-location-sub"><strong>Sub Album</strong><span>{location.subAlbum}</span></small>}</div>;
}
