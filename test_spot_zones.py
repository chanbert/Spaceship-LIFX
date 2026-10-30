import unittest,struct
from unittest.mock import patch
from lifx import Lights,spot_colors
class SpotTests(unittest.TestCase):
 def test_spot_packet_and_restore(self):
  d=dict(mac='000000000001',role='A',product=171);r=Lights([d]);orig=[struct.pack('<HHHH',i*100,200,300,6500) for i in range(3)];r.zone_original[d['mac']]=orig;r.original[d['mac']]=(orig[0],0)
  with patch.object(r,'send') as send:
   r.apply(dict(hue=200,saturation=.8,brightness=1,fade=120,time=2,cue_id='S002'),.6)
   packet=send.call_args_list[0].args;self.assertEqual(packet[1],715);self.assertEqual(len(packet[2]),522);self.assertEqual(struct.unpack('<6BI',packet[2][:10]),(0,1,0,0,0,3,120));self.assertEqual(len(set(packet[2][10+i*8:18+i*8] for i in range(3))),3)
   send.reset_mock();r.restore();self.assertEqual(send.call_args_list[0].args[2][10:34],b''.join(orig))
 def test_blackout(self):
  c=dict(hue=0,saturation=1,brightness=0,time=3)
  self.assertTrue(all(struct.unpack('<HHHH',x)[2]==0 for x in spot_colors(c,1,'B')))
if __name__=='__main__':unittest.main()
