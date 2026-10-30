"""Loopback-only show player. Browser owns audio; server schedules LIFX cues."""
import argparse
import bisect, json, secrets, threading, time, webbrowser, signal, sys, re, os
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from lifx import Lights, discover, CaptureError

ROOT = Path(__file__).resolve().parent
EDITION = ROOT / 'editions/ship-wouldnt-open'
SHOW = json.loads((EDITION / 'show.json').read_text(encoding='utf-8'))
WORDS = json.loads((EDITION / 'words.json').read_text(encoding='utf-8'))
TOKEN = secrets.token_urlsafe(32)
PORT = 8765
ROLES = {
    'G': {'name': 'Ground', 'position': 'Low to the ground', 'use': 'Hatch, tools, engine, and small visitors.'},
    'A': {'name': 'Tree 1', 'position': 'First area of the tree', 'use': 'Small-ship energy and outgoing radio calls.'},
    'B': {'name': 'Tree 2', 'position': 'A different area of the same tree', 'use': 'Distant replies and the larger ship arriving above.'},
}
MAPPING_PATH = ROOT / 'light-assignments.json'
MAPPING_LOCK = threading.RLock()

def validate_assignments(assignments):
    if not isinstance(assignments, dict): raise ValueError('Assignments must map device IDs to G, A, or B.')
    for mac, role in assignments.items():
        if not re.fullmatch(r'[0-9a-f]{12}', mac) or role not in ROLES:
            raise ValueError('Each light must have one valid role: G, A, or B.')
    return dict(assignments)

def read_assignments():
    with MAPPING_LOCK:
        if MAPPING_PATH.exists(): return validate_assignments(json.loads(MAPPING_PATH.read_text(encoding='utf-8')))
        return {}

def save_assignments(assignments):
    clean = validate_assignments(assignments)
    with MAPPING_LOCK:
        temp = MAPPING_PATH.with_suffix('.tmp')
        temp.write_text(json.dumps(clean, indent=2))
        os.replace(temp, MAPPING_PATH)
    return clean

def read_devices():
    path = ROOT / 'lights.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []

def targets(cue):
    return cue.get('roles', list(ROLES))

def state_at(cues, position, delay, role):
    state = (225., .85, 0.)
    origin, start, duration = state, 0., 0.
    def interpolate(at):
        f = min(1., max(0., (at-start)/duration)) if duration else 1.
        dh = (state[0]-origin[0]+180)%360-180
        return ((origin[0]+dh*f)%360, origin[1]+(state[1]-origin[1])*f, origin[2]+(state[2]-origin[2])*f)
    for cue in cues:
        at = cue['time'] + delay
        if at > position: break
        if role not in targets(cue): continue
        origin = interpolate(at)
        state = (cue['hue'], cue['saturation'], cue['brightness'])
        start, duration = at, cue['fade']/1000
    return interpolate(position)


class Lighting:
    def __init__(self):
        self.lock = threading.RLock()
        self.rig = None
        self.session = None
        self.error = ''
        self.playing = False
        self.position = 0
        self.last = time.monotonic()
        self.index = 0
        self.seq = -1
    def stop(self):
        with self.lock:
            rig, self.rig = self.rig, None
            self.session = None
            self.playing = False
            if rig:
                try: rig.restore()
                except Exception as e: self.error = 'Light restoration failed: ' + str(e)
    def start(self, data):
        with self.lock:
            if self.rig: raise ValueError('A lighting session is already active. Stop it first.')
            devices = read_devices()
            assignments = validate_assignments(data.get('assignments', {}))
            if not assignments: raise ValueError('Assign at least one light to G, A, or B.')
            def choose(known):
                return [dict(d, role=assignments[d['mac']]) for d in known if d['mac'] in assignments]
            if set(assignments)-{d['mac'] for d in devices}: devices=discover(seconds=4)
            chosen = choose(devices)
            unknown=[{'mac':m,'label':m,'role':r} for m,r in assignments.items() if m not in {d['mac'] for d in chosen}]
            if not chosen: raise ValueError('No assigned lights are reachable. Rescan or check their power and Wi-Fi.')
            self.skipped=[]
            cap, delay = float(data['cap']), float(data['delay'])
            if not .01 <= cap <= 1 or not -1 <= delay <= 2: raise ValueError('Invalid lighting settings.')
            rig = Lights(chosen)
            try:
                rig.capture()
            except CaptureError as error:
                # Keep successfully captured fixtures and their original states.
                missing={d['mac'] for d in error.missing}
                self.skipped=[dict(d) for d in error.missing]
                chosen=[d for d in chosen if d['mac'] not in missing]
                if not chosen:
                    rig.sock.close()
                    raise ValueError('None of the assigned lights responded. Rescan or check power and Wi-Fi.')
                rig.devices=chosen
            except Exception:
                rig.sock.close()
                raise
            self.skipped+=unknown
            self.rig = rig
            self.cap, self.delay = cap, delay
            self.active_roles = sorted({d['role'] for d in chosen})
            self.session = secrets.token_urlsafe(16)
            self.seq = -1
            self.index = 0
            self.position = 0
            self.last = time.monotonic()
            self.playing = False
            self.error = ''
            return self.session
    def clock(self, data):
        with self.lock:
            if not self.rig or data.get('session') != self.session: return
            seq = int(data['seq'])
            if seq <= self.seq: return
            self.seq = seq
            pos = float(data['position'])
            if not 0 <= pos <= SHOW['duration'] + 1: raise ValueError('Invalid audio position.')
            now = time.monotonic()
            estimated = self.position + (now - self.last if self.playing else 0)
            jump = bool(data.get('seek')) or abs(pos - estimated) > .5 or bool(data['playing']) != self.playing
            self.position, self.last, self.playing = pos, now, bool(data['playing'])
            if jump:
                times = [c['time'] + self.delay for c in SHOW['cues']]
                self.index = bisect.bisect_right(times, pos)
                for role in self.active_roles:
                    h, s, b = state_at(SHOW['cues'], pos, self.delay, role)
                    active = next((c for c in reversed(SHOW['cues'][:self.index]) if role in targets(c)), {})
                    self.rig.apply(dict(active, hue=h, saturation=s, brightness=b, fade=0, roles=[role]), self.cap)
                    if self.playing:
                        active = next((c for c in reversed(SHOW['cues'][:self.index]) if role in targets(c)), None)
                        if active:
                            remaining = active['time'] + self.delay + active['fade']/1000 - pos
                            if remaining > 0: self.rig.apply(dict(active, roles=[role], fade=round(remaining*1000)), self.cap)
    def run(self):
        while True:
            time.sleep(.015)
            with self.lock:
                if not self.rig: continue
                if time.monotonic() - self.last > 8:
                    self.error = 'Browser disconnected; lights restored.'
                    self.stop()
                    continue
                if not self.playing: continue
                pos = self.position + time.monotonic() - self.last
                try:
                    while self.index < len(SHOW['cues']) and SHOW['cues'][self.index]['time'] + self.delay <= pos:
                        self.rig.apply(SHOW['cues'][self.index], self.cap)
                        self.index += 1
                except Exception as e:
                    self.error = str(e)
                    self.stop()

lighting = Lighting()
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)
    def allowed(self):
        return self.headers.get('Host') in (f'127.0.0.1:{PORT}', f'localhost:{PORT}')
    def do_GET(self):
        if not self.allowed(): return self.json({'error': 'Invalid host'}, 403)
        path = urlparse(self.path).path
        if path == '/api/show': return self.json({'show': SHOW, 'token': TOKEN, 'words': WORDS})
        if path == '/api/assignments': return self.json({'roles': ROLES, 'assignments': read_assignments()})
        if path == '/api/devices': return self.json(read_devices())
        if path == '/api/status': return self.json({'active': bool(lighting.rig), 'error': lighting.error})
        files = {'/': ROOT / 'web/index.html', '/app.js': ROOT / 'web/app.js', '/style.css': ROOT / 'web/style.css', '/audio.wav': EDITION / 'audio/demo.wav', '/script.txt': EDITION / 'script.txt'}
        file = files.get(path)
        if not file or not file.exists(): return self.json({'error': 'Not found'}, 404)
        mime = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.wav': 'audio/wav', '.txt': 'text/plain; charset=utf-8'}[file.suffix]
        size = file.stat().st_size
        start, end, partial = 0, size - 1, False
        r = self.headers.get('Range')
        if r:
            try:
                unit, bounds = r.split('='); a, b = bounds.split('-')
                if unit != 'bytes': raise ValueError()
                start = int(a) if a else max(0, size - int(b))
                end = min(int(b), size - 1) if b and a else size - 1
                if not 0 <= start <= end < size: raise ValueError()
                partial = True
            except ValueError:
                self.send_response(416); self.send_header('Content-Range', f'bytes */{size}'); self.end_headers(); return
        self.send_response(206 if partial else 200)
        self.send_header('Content-Type', mime)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(end - start + 1))
        if partial: self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        try:
            with file.open('rb') as f:
                f.seek(start); remaining = end - start + 1
                while remaining:
                    chunk = f.read(min(65536, remaining))
                    if not chunk: break
                    self.wfile.write(chunk); remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError): pass
    def do_POST(self):
        if not self.allowed(): return self.json({'error': 'Invalid host'}, 403)
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length < 65536: raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(length))
            if data.get('token') != TOKEN: return self.json({'error': 'Invalid token'}, 403)
            if self.path == '/api/assignments':
                if lighting.rig: raise ValueError('Stop lighting playback before changing assignments.')
                return self.json({'assignments': save_assignments(data.get('assignments'))})
            if self.path == '/api/start': return self.json({'session': lighting.start(data), 'skipped': lighting.skipped})
            if self.path == '/api/clock': lighting.clock(data)
            elif self.path == '/api/stop': lighting.stop()
            elif self.path == '/api/discover':
                if lighting.rig: raise ValueError('Stop lighting playback before discovering devices.')
                return self.json(discover())
            else: return self.json({'error': 'Not found'}, 404)
            return self.json({'ok': True})
        except Exception as e: return self.json({'error': str(e)}, 400)

def main():
    global PORT
    parser = argparse.ArgumentParser(description='Local Spaceship-LIFX player')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535: parser.error('port must be between 1 and 65535')
    PORT = args.port
    try:
        server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    except OSError as error:
        print(f'Could not start on port {PORT}: {error}. Close another player instance and try again.', file=sys.stderr)
        return 1
    threading.Thread(target=lighting.run, daemon=True).start()
    print(f'Spaceship-LIFX: http://127.0.0.1:{PORT}', flush=True)
    if '--no-browser' not in sys.argv: webbrowser.open(f'http://127.0.0.1:{PORT}')
    def shutdown(signum, frame):
        lighting.stop()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, shutdown)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: lighting.stop(); server.server_close()
if __name__ == '__main__': sys.exit(main())
