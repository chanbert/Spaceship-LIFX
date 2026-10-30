"""Small LIFX LAN client. Discovery is read-only; all writes require explicit targets."""
import math, json, re, socket, struct, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SOURCE=0x48414c4c

def packet(kind, payload=b'', mac=None, sequence=0):
 p=bytearray(36)
 struct.pack_into('<HHI',p,0,36+len(payload),0x1400 if mac else 0x3400,SOURCE)
 if mac:p[8:14]=bytes.fromhex(mac)
 p[23]=sequence%256
 struct.pack_into('<H',p,32,kind)
 return bytes(p)+payload

class CaptureError(RuntimeError):
 def __init__(self, missing):
  self.missing=missing
  labels=', '.join(f"{d.get('label',d['mac'])}"+(f" ({d['role']})" if d.get('role') else '') for d in missing)
  super().__init__(f"Cannot reach: {labels}. Turn these lights on and check Wi-Fi, or set them to Not used. No lighting changes made.")

def merge_discovered(previous, found):
 now=time.time()
 registry={d['mac']:dict(d,online=False) for d in previous}
 for d in found:
  registry[d['mac']]={**registry.get(d['mac'],{}),**d,'online':True,'last_seen':now}
 return sorted(registry.values(),key=lambda d:d.get('label',d['mac']))

def discover(seconds=8):
 found={}
 interfaces=subprocess.check_output(['/sbin/ifconfig'],text=True)
 broadcasts=set(re.findall(r'broadcast (\d+\.\d+\.\d+\.\d+)',interfaces))|{'255.255.255.255'}
 with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
  s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1);s.bind(('',0));s.settimeout(.15)
  end=time.monotonic()+seconds;last=0
  while time.monotonic()<end:
   if time.monotonic()-last>1:
    for ip in broadcasts:
     try:s.sendto(packet(2),(ip,56700))
     except OSError:pass
    for x in found.values():
     for kind in (23,32,51,511):s.sendto(packet(kind,mac=x['mac']),(x['ip'],x['port']))
    last=time.monotonic()
   try:d,a=s.recvfrom(4096)
   except socket.timeout:continue
   if len(d)<36 or struct.unpack_from('<I',d,4)[0]!=SOURCE:continue
   mac=d[8:14].hex();kind=struct.unpack_from('<H',d,32)[0]
   if kind==3 and len(d)>=41 and d[36]==1:
    found.setdefault(mac,{'mac':mac,'ip':a[0],'port':struct.unpack_from('<I',d,37)[0]})
   x=found.get(mac)
   if x is None:continue
   if kind==512 and len(d)>=41:x['zone_count']=struct.unpack_from('<H',d,36)[0]
   if kind==25 and len(d)>=68:x['label']=d[36:68].split(b'\0')[0].decode(errors='replace')
   if kind==33 and len(d)>=48:x['product']=struct.unpack_from('<I',d,40)[0]
   if kind==53 and len(d)>=84:x['group']=d[52:84].split(b'\0')[0].decode(errors='replace')
 previous=json.loads((ROOT/'lights.json').read_text()) if (ROOT/'lights.json').exists() else []
 result=merge_discovered(previous,list(found.values()))
 (ROOT/'lights.json').write_text(json.dumps(result,indent=2));return result

def ground_colors(cue,count,limit):
 """Deterministic spatial pattern: seeking to a cue reproduces its zones."""
 out=[];at=cue.get('time',0);cid=cue.get('cue_id','');name=cue.get('name','').lower()
 for i in range(count):
  pos=i/max(1,count-1);h=cue['hue'];sat=cue['saturation'];b=cue['brightness']
  if cid=='IDLE':
   h=[180,260,115][i%3];sat=.7;b*=.8+.2*math.sin(i*1.7)**2
  elif cid=='GROUND':
   center=(at*.65)%1
   distance=min(abs(pos-center),1-abs(pos-center))
   active=distance<(.18 if 'goop' in name else .12)
   if 'red' in name:active=(i+int(at*5))%2==0
   if not active:h=[180,260,115][i%3];sat=.7;b=.28
  elif b>0:
   # Moving highlights leave neighboring sections in a contrasting color.
   wave=(1+math.sin(pos*math.pi*2-at*4))/2
   h=(h+(1-wave)*35)%360;b*=.55+.45*wave
  out.append(struct.pack('<HHHH',round(h/360*65535),round(sat*65535),round(max(0,min(1,b*limit))*65535),6500))
 return out

def spot_colors(cue,limit,role):
 # Three emitter regions: bright core, contrasting shoulders; phase mirrored across trees.
 colors=[];h=cue['hue'];sat=cue['saturation'];b=cue['brightness'];at=cue.get('time',0)
 for i in range(3):
  phase=(i+(1 if role=='B' else 0)+int(at*4))%3
  hue=(h+[-25,0,30][phase])%360
  brightness=b*(1 if phase==1 else .82)
  saturation=sat*(.45 if phase==1 and b>.7 else 1)
  if cue.get('cue_id')=='IDLE':hue=(h+[-35,0,35][i])%360
  colors.append(struct.pack('<HHHH',round(hue/360*65535),round(saturation*65535),round(max(0,min(1,brightness*limit))*65535),6500))
 return colors

class Lights:
 def __init__(self, devices):
  self.devices=devices;self.original={};self.zone_original={};self.seq=0
  self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.sock.bind(('',0));self.sock.settimeout(.15)
 def send(self,x,kind,payload=b''):
  self.seq+=1;self.sock.sendto(packet(kind,payload,x['mac'],self.seq),(x['ip'],x['port']))
 def capture_zones(self):
  collected={};counts={}
  for attempt in range(2):
   for x in self.devices:
    try:
     if x.get('product')==171:
      x['zone_count']=3;x['matrix_width']=3
      self.send(x,707,struct.pack('<6B',0,1,0,0,0,3))
     else:self.send(x,511)
    except OSError:pass
   end=time.monotonic()+.6
   while time.monotonic()<end:
    try:d,_=self.sock.recvfrom(4096)
    except socket.timeout:continue
    if len(d)>=553 and struct.unpack_from('<I',d,4)[0]==SOURCE and struct.unpack_from('<H',d,32)[0]==711:
     mac=d[8:14].hex()
     if any(x['mac']==mac and x.get('product')==171 for x in self.devices) and d[36]==0 and d[40]==3:
      counts[mac]=3;collected[mac]={i:d[41+8*i:49+8*i] for i in range(3)}
     continue
    if len(d)<41 or struct.unpack_from('<I',d,4)[0]!=SOURCE or struct.unpack_from('<H',d,32)[0]!=512:continue
    mac=d[8:14].hex()
    if mac not in {x['mac'] for x in self.devices}:continue
    total,start,n=struct.unpack_from('<HHB',d,36)
    if not 1<total<=4096 or n>82 or start+n>total or len(d)<41+n*8:continue
    counts[mac]=total;zones=collected.setdefault(mac,{})
    for i in range(n):zones[start+i]=d[41+8*i:49+8*i]
  for x in self.devices:
   mac=x['mac'];n=counts.get(mac,x.get('zone_count',0))
   if n>1:
    x['zone_count']=n
    if len(collected.get(mac,{}))==n:self.zone_original[mac]=[collected[mac][i] for i in range(n)]
 def send_zones(self,x,colors,fade):
  if x.get('product')==171:
   self.send(x,715,struct.pack('<6BI',0,1,0,0,0,3,fade)+b''.join(colors[:3])+bytes(61*8))
   return
  for start in range(0,len(colors),82):
   chunk=colors[start:start+82];apply=1 if start+len(chunk)==len(colors) else 0
   payload=struct.pack('<IBHB',fade,apply,start,len(chunk))+b''.join(chunk)+bytes((82-len(chunk))*8)
   self.send(x,510,payload)
 def capture(self):
  self.capture_zones()
  for attempt in range(3):
   for x in self.devices:
    if x['mac'] not in self.original:
     try:self.send(x,101)
     except OSError:pass
   end=time.monotonic()+.6
   while time.monotonic()<end:
    try:d,_=self.sock.recvfrom(4096)
    except socket.timeout:continue
    if len(d)>=48 and struct.unpack_from('<I',d,4)[0]==SOURCE and struct.unpack_from('<H',d,32)[0]==107:
     self.original[d[8:14].hex()]=(d[36:44],struct.unpack_from('<H',d,46)[0])
   if all(x['mac'] in self.original for x in self.devices):break
  missing=[x for x in self.devices if x['mac'] not in self.original or (x.get('zone_count',0)>1 and x['mac'] not in self.zone_original)]
  if missing:raise CaptureError(missing)
 def apply(self,cue,limit):
  h=int(cue['hue']/360*65535);s=int(cue['saturation']*65535);b=int(cue['brightness']*limit*65535)
  payload=struct.pack('<BHHHHI',0,h,s,b,6500,cue['fade'])
  for x in self.devices:
   if cue.get('roles') is not None and x.get('role') not in cue['roles']:continue
   try:
    if (x.get('role')=='G' or x.get('product')==171) and x['mac'] in self.zone_original:
     self.send_zones(x,spot_colors(cue,limit,x.get('role')) if x.get('product')==171 else ground_colors(cue,len(self.zone_original[x['mac']]),limit),cue['fade'])
    else:self.send(x,102,payload)
    self.send(x,117,struct.pack('<HI',65535,0))
   except OSError:continue
 def restore(self):
  for x in self.devices:
   if x['mac'] in self.original:
    color,power=self.original[x['mac']]
    for _ in range(2):
     try:
      if x['mac'] in self.zone_original:self.send_zones(x,self.zone_original[x['mac']],300)
      else:self.send(x,102,b'\0'+color+struct.pack('<I',300))
      self.send(x,117,struct.pack('<HI',power,300))
     except OSError:continue
  self.sock.close()

if __name__=='__main__':print(json.dumps(discover(),indent=2))
