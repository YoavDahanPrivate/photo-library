"""Report production path isolation without importing/migrating the databases."""
import ctypes,importlib,json,os,site,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent;STORAGE=ROOT.parent
assert sys.flags.isolated==1 and not site.ENABLE_USER_SITE
assert Path(sys.executable).resolve().is_relative_to(ROOT)
assert all(Path(p).resolve().is_relative_to(ROOT) for p in sys.path),sys.path
modules={}
for name in ('fastapi','uvicorn','numpy','cv2','PIL','pillow_heif','imageio_ffmpeg','httpx','webauthn','cbor2','cryptography','OpenSSL','sqlite3','ssl'):
 module=importlib.import_module(name);path=Path(module.__file__).resolve()
 assert path.is_relative_to(ROOT),(name,str(path));modules[name]=str(path)
import cv2,imageio_ffmpeg,numpy as np
ffmpeg=Path(imageio_ffmpeg.get_ffmpeg_exe());assert ffmpeg.resolve().is_relative_to(ROOT)
subprocess.run([str(ffmpeg),'-version'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
detector=cv2.FaceDetectorYN.create(str(STORAGE/'models'/'yunet.onnx'),'',(320,320),0.9,0.3,1000)
detector.detect(np.zeros((320,320,3),dtype=np.uint8));cv2.FaceRecognizerSF.create(str(STORAGE/'models'/'sface.onnx'),'')
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
enum=kernel.K32EnumProcessModules;enum.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p),ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32)];enum.restype=ctypes.c_int
module_name=kernel.GetModuleFileNameW;module_name.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint32];module_name.restype=ctypes.c_uint32
handles=(ctypes.c_void_p*2048)();needed=ctypes.c_uint32()
if not enum(ctypes.c_void_p(-1),handles,ctypes.sizeof(handles),ctypes.byref(needed)):raise ctypes.WinError(ctypes.get_last_error())
if needed.value>ctypes.sizeof(handles):raise RuntimeError('Loaded module audit buffer was too small')
windows=Path(os.environ.get('SystemRoot',r'C:\Windows')).resolve()
defender=(Path(os.environ.get('ProgramData',r'C:\ProgramData'))/'Microsoft/Windows Defender/Platform').resolve();native=[]
for handle in list(handles)[:needed.value//ctypes.sizeof(ctypes.c_void_p)]:
 buffer=ctypes.create_unicode_buffer(32768)
 if not module_name(handle,buffer,len(buffer)):raise ctypes.WinError(ctypes.get_last_error())
 path=Path(buffer.value).resolve();native.append(str(path))
 if not (path.is_relative_to(ROOT) or path.is_relative_to(windows) or path.is_relative_to(defender)):raise RuntimeError('Native dependency outside production package/Windows: '+str(path))
result={'passed':True,'python':sys.executable,'paths':sys.path,'modules':modules,'native_modules':native,'ffmpeg':str(ffmpeg),'models':str(STORAGE/'models'),'host_user_packages_used':False}
print(json.dumps(result),flush=True)
