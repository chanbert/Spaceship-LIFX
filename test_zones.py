import unittest,struct
from unittest.mock import patch
from lifx import Lights,ground_colors
class ZoneTests(unittest.TestCase):
 def test_ground_palette_and_limit(self):
  c=dict(hue=160,saturation=.65,brightness=.34,fade=100,cue_id='IDLE',time=0)
  z=ground_colors(c,13,.5);self.assertEqual(len(z),13);self.assertGreater(len(set(z)),2)
  self.assertTrue(all(struct.unpack('<HHHH',v)[2]<=.5*65535 for v in z))
 def test_packets_restore_and_fallback(self):
  a=dict(mac='000000000001',role='G');b=dict(mac='000000000002',role='A');r=Lights([a,b]);colors=[struct.pack('<HHHH',i,100,200,6500) for i in range(100)];r.zone_original[a['mac']]=colors;r.original[a['mac']]=(colors[0],0)
  with patch.object(r,'send') as send:
   r.apply(dict(hue=120,saturation=1,brightness=.8,fade=80,cue_id='GROUND',name='Green goop',time=3),.5)
   packets=[c.args for c in send.call_args_list if c.args[1]==510];self.assertEqual(len(packets),2)
   self.assertEqual(struct.unpack('<IBHB',packets[0][2][:8]),(80,0,0,82));self.assertEqual(struct.unpack('<IBHB',packets[1][2][:8]),(80,1,82,18))
   self.assertTrue(any(c.args[0]==b and c.args[1]==102 for c in send.call_args_list))
   send.reset_mock();r.restore();packets=[c.args for c in send.call_args_list if c.args[1]==510];self.assertEqual(packets[0][2][8:664],b''.join(colors[:82]))
if __name__=='__main__':unittest.main()
