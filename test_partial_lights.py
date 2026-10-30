import unittest,json
from unittest.mock import patch,Mock
import web_server as web
from lifx import CaptureError,Lights
class Partial(unittest.TestCase):
 def test_one_missing_keeps_other_and_original(self):
  devices=[{'mac':'000000000001'},{'mac':'000000000002'}][:2]
  class Rig:
   def __init__(self,ds):self.devices=ds;self.original={ds[0]['mac']:'saved'};self.sock=Mock()
   def capture(self):raise CaptureError([self.devices[1]])
   def restore(self):pass
  with patch.object(web,'Lights',Rig), patch.object(web,'read_devices',return_value=devices):
   l=web.Lighting();l.start({'assignments':{d['mac']:'A' for d in devices},'cap':.5,'delay':0})
   self.assertEqual(len(l.rig.devices),1);self.assertEqual(len(l.skipped),1);self.assertEqual(l.rig.original[devices[0]['mac']],'saved');l.stop()
 def test_all_missing_does_not_start(self):
  devices=[{'mac':'000000000001'},{'mac':'000000000002'}][:1]
  class Rig:
   def __init__(self,ds):self.devices=ds;self.sock=Mock()
   def capture(self):raise CaptureError(self.devices)
  with patch.object(web,'Lights',Rig), patch.object(web,'read_devices',return_value=devices):
   l=web.Lighting()
   with self.assertRaisesRegex(ValueError,'None of'):l.start({'assignments':{devices[0]['mac']:'A'},'cap':.5,'delay':0})
   self.assertIsNone(l.rig)
 def test_send_failure_does_not_block_next_fixture(self):
  ds=[{'mac':'000000000001','role':'A'},{'mac':'000000000002','role':'A'}];rig=Lights(ds)
  try:
   calls=[]
   def send(d,*args):
    calls.append(d['mac'])
    if d==ds[0]:raise OSError('offline')
   with patch.object(rig,'send',side_effect=send):rig.apply(dict(hue=120,saturation=1,brightness=.7,fade=100,roles=['A']),.5)
   self.assertIn(ds[1]['mac'],calls)
  finally:rig.sock.close()
if __name__=='__main__':unittest.main()
