import tempfile
from pathlib import Path
import json, threading, unittest, urllib.request, urllib.error, wave
from unittest.mock import patch
import web_server as web

class Rig:
    def __init__(self, devices): self.devices=devices;self.applied=[];self.restored=False
    def capture(self): pass
    def apply(self,cue,cap): self.applied.append((cue,cap))
    def restore(self): self.restored=True

class Tests(unittest.TestCase):
    def test_fresh_install_has_no_devices(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(web, 'ROOT', Path(folder)):
            self.assertEqual(web.read_devices(), [])

    def test_seek_and_stale_clock(self):
        with patch.object(web,'Lights',Rig), patch.object(web,'read_devices',return_value=[{'mac':'000000000001'}]):
            l=web.Lighting();devices=web.read_devices()
            session=l.start({'assignments':{devices[0]['mac']:'A'},'cap':.5,'delay':.2})
            rig=l.rig
            l.clock({'session':session,'seq':2,'position':100,'playing':True,'seek':True})
            self.assertGreater(l.index,0);self.assertTrue(rig.applied)
            l.clock({'session':session,'seq':1,'position':0,'playing':True})
            self.assertEqual(l.position,100)
            l.stop();self.assertTrue(rig.restored)
            l.start({'assignments':{devices[0]['mac']:'A'},'cap':.5,'delay':.2})
            self.assertEqual(l.index,0);l.stop()
    def test_independent_roles_and_multiple_fixtures(self):
        from lifx import Lights
        devices=[{'mac':'000000000001','role':'G'}, {'mac':'000000000002','role':'A'}, {'mac':'000000000003','role':'A'}, {'mac':'000000000004','role':'B'}]
        rig=Lights(devices)
        try:
            with patch.object(rig,'send') as send:
                rig.apply(dict(hue=120,saturation=1,brightness=.5,fade=100,roles=['A']),.5)
                self.assertEqual({call.args[0]['mac'] for call in send.call_args_list},{'000000000002','000000000003'})
                self.assertEqual(send.call_count,4)
                send.reset_mock()
                rig.apply(dict(hue=120,saturation=1,brightness=.5,fade=100),.5)
                self.assertEqual(send.call_count,8)
        finally:rig.sock.close()
    def test_role_seek_preserves_each_state(self):
        cues=[dict(time=0,hue=220,saturation=.8,brightness=.1,fade=0),dict(time=5,hue=120,saturation=1,brightness=.8,fade=1000,roles=['A']),dict(time=6,hue=30,saturation=1,brightness=.4,fade=0,roles=['B'])]
        self.assertAlmostEqual(web.state_at(cues,7,0,'G')[2],.1)
        self.assertAlmostEqual(web.state_at(cues,7,0,'A')[2],.8)
        self.assertAlmostEqual(web.state_at(cues,7,0,'B')[2],.4)
        self.assertAlmostEqual(web.state_at(cues,5.5,0,'A')[2],.45)
        self.assertAlmostEqual(web.state_at(cues,0,0,'A')[2],.1)
    def test_assignment_persistence(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder, patch.object(web,'MAPPING_PATH',Path(folder)/'roles.json'):
            self.assertEqual(web.read_assignments(),{})
            assignment={'000000000001':'G','000000000002':'G','000000000003':'B'}
            web.save_assignments(assignment)
            self.assertEqual(web.read_assignments(),assignment)
            with self.assertRaises(ValueError):web.save_assignments({'000000000001':'C'})
            self.assertEqual(web.read_assignments(),assignment)
    def test_show_matches_audio(self):
        s=web.SHOW
        with wave.open(str(web.EDITION/'audio/demo.wav')) as f:
            self.assertAlmostEqual(f.getnframes()/f.getframerate(),s['duration'],places=2)
        self.assertEqual(len([e for e in s['events'] if not e.get('intermission')]),len(json.loads((web.EDITION/'script.json').read_text(encoding='utf-8'))['scenes']))
        self.assertTrue(all(0<=c['time']<s['duration'] for c in s['cues']))
        self.assertTrue(all(l['time']<l['end']<=s['duration'] for l in s['lines']))
        self.assertTrue(all(e['next_scene']-e['quiet_start']<14 for e in s['events'] if not e.get('intermission')))
    def test_http_range_and_auth(self):
        server=web.ThreadingHTTPServer(('127.0.0.1',0),web.Handler)
        with patch.object(web,'PORT',server.server_port):
            threading.Thread(target=server.serve_forever,daemon=True).start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                req=urllib.request.Request(base+'/audio.wav',headers={'Range':'bytes=0-43'})
                with urllib.request.urlopen(req) as r:
                    self.assertEqual(r.status,206);self.assertEqual(len(r.read()),44)
                req=urllib.request.Request(base+'/api/start',data=b'{"token":"bad"}',headers={'Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as err: urllib.request.urlopen(req)
                self.assertEqual(err.exception.code,403)
                with urllib.request.urlopen(base+'/api/show') as r: self.assertEqual(json.load(r)['show']['title'],web.SHOW['title'])
            finally: server.shutdown();server.server_close()
if __name__=='__main__': unittest.main()
