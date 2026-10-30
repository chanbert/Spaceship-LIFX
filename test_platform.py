import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest.mock import patch
import lifx

class DiscoveryTests(unittest.TestCase):
    def test_windows_subnets_and_loopback(self):
        rows=[{'IPAddress':'192.0.2.10','PrefixLength':24}, {'IPAddress':'198.51.100.10','PrefixLength':25}, {'IPAddress':'127.0.0.1','PrefixLength':8}]
        with patch.object(lifx.sys,'platform','win32'), patch.object(lifx.subprocess,'check_output',return_value=json.dumps(rows)):
            self.assertEqual(lifx.broadcast_addresses(),{'255.255.255.255','192.0.2.255','198.51.100.127'})
    def test_single_windows_interface(self):
        with patch.object(lifx.sys,'platform','win32'), patch.object(lifx.subprocess,'check_output',return_value='{"IPAddress":"192.0.2.10","PrefixLength":24}'):
            self.assertIn('192.0.2.255',lifx.broadcast_addresses())
    def test_discovery_fallback(self):
        with patch.object(lifx.subprocess,'check_output',side_effect=OSError):
            self.assertEqual(lifx.broadcast_addresses(),{'255.255.255.255'})
    def test_macos_broadcast(self):
        with patch.object(lifx.sys,'platform','darwin'), patch.object(lifx.subprocess,'check_output',return_value='inet 192.0.2.10 netmask 0xffffff00 broadcast 192.0.2.255'):
            self.assertIn('192.0.2.255',lifx.broadcast_addresses())
    @unittest.skipUnless(sys.platform=='win32','Windows adapter integration')
    def test_real_windows_adapters(self):
        command='Get-NetIPAddress -AddressFamily IPv4 | Select-Object IPAddress,PrefixLength | ConvertTo-Json -Compress'
        rows=json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],text=True,timeout=10))
        self.assertTrue(rows)
        self.assertGreater(len(lifx.broadcast_addresses()),1)

class StartupTests(unittest.TestCase):
    def test_clean_startup_and_audio(self):
        root=Path(__file__).resolve().parent
        # Exercise the actual Windows launcher, including a working directory with spaces.
        import shutil
        with tempfile.TemporaryDirectory(prefix='spaceship test ') as folder:
            dest=Path(folder)/'app with spaces'
            shutil.copytree(root,dest,ignore=shutil.ignore_patterns('.git','__pycache__','lights.json','light-assignments.json'))
            env=dict(os.environ,SPACESHIP_TEST_MODE='1',PYTHONUTF8='1')
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            base=f'http://127.0.0.1:{port}'
            args=['cmd.exe','/c','Start Web Player.bat','--no-browser','--port',str(port)] if sys.platform=='win32' else [sys.executable,'web_server.py','--no-browser','--port',str(port)]
            with tempfile.TemporaryFile() as log:
                proc=subprocess.Popen(args,cwd=dest,env=env,stdout=log,stderr=log)
                try:
                    deadline=time.monotonic()+20
                    while True:
                        if proc.poll() is not None:
                            log.seek(0);self.fail(log.read().decode(errors='replace'))
                        try:
                            with urllib.request.urlopen(base+'/api/devices',timeout=1) as r:
                                self.assertEqual(json.load(r),[])
                            break
                        except OSError:
                            if time.monotonic()>deadline:raise
                            time.sleep(.2)
                    for path in ('/','/app.js','/style.css','/api/show','/script.txt'):
                        with urllib.request.urlopen(base+path) as r:self.assertTrue(r.read())
                    with urllib.request.urlopen(base+'/api/assignments') as r:self.assertEqual(json.load(r)['assignments'],{})
                    req=urllib.request.Request(base+'/audio.wav',headers={'Range':'bytes=0-43'})
                    with urllib.request.urlopen(req) as r:
                        self.assertEqual(r.status,206);self.assertEqual(r.read()[:4],b'RIFF')
                finally:
                    if sys.platform=='win32':subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    else:proc.terminate()
                    proc.wait(timeout=10)
