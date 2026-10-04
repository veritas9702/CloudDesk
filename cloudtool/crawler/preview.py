"""Loopback-only static preview lifecycle; no access outside capture root."""
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def list_directory(self, path):
        self.send_error(403, 'Directory listing disabled')

    def send_head(self):
        path = Path(self.translate_path(self.path))
        if not path.resolve().is_relative_to(Path(self.directory).resolve()):
            self.send_error(403)
            return None
        return super().send_head()


class Preview:
    def __init__(self):
        self.server = None

    def open(self, folder):
        self.close()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(folder)))
        self.server.daemon_threads = True
        Thread(target=self.server.serve_forever, kwargs={'poll_interval': .1}, daemon=True).start()
        return f'http://127.0.0.1:{self.server.server_port}/index.html'

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
