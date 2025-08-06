import os
import threading
import select
import fcntl
import termios
import struct
import pty
import tty
import subprocess
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_socketio import SocketIO, emit, disconnect
from dotenv import load_dotenv

load_dotenv()

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")
PORT = int(os.environ.get("PORT", 8000))

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = SECRET_KEY
socketio = SocketIO(app, async_mode="eventlet")

# Keep mapping of socket session -> pty master fd & thread
clients = {}

def set_pty_size(fd, rows, cols):
    # set terminal size for pty
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

def read_and_forward(sid, master_fd):
    """Read from pty master and forward to client socket."""
    try:
        while True:
            rf, _, _ = select.select([master_fd], [], [], 0.1)
            if master_fd in rf:
                try:
                    data = os.read(master_fd, 1024)
                except OSError:
                    break
                if not data:
                    break
                socketio.emit('pty-output', {'output': data.decode(errors='ignore')}, room=sid)
    except Exception as e:
        socketio.emit('pty-output', {'output': f'\n[connection error: {e}]\n'}, room=sid)
    finally:
        # cleanup: notify client, close socket-side pty if exists
        try:
            os.close(master_fd)
        except Exception:
            pass
        socketio.emit('pty-output', {'output': '\n[session closed]\n'}, room=sid)
        # disconnect client
        try:
            socketio.disconnect(sid)
        except Exception:
            pass
        clients.pop(sid, None)

@app.route('/', methods=['GET'])
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return redirect(url_for('terminal'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        if u == ADMIN_USER and p == ADMIN_PASS:
            session['logged_in'] = True
            session['user'] = u
            return redirect(url_for('terminal'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/terminal')
def terminal():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('terminal.html')

@socketio.on('connect')
def ws_connect():
    sid = request.sid
    # require session login
    if not session.get('logged_in'):
        # refuse connection
        return False

@socketio.on('start-pty')
def start_pty(data):
    """
    Client requests to start a new PTY session.
    We spawn /bin/bash (or /bin/sh fallback) with forkpty and forward IO.
    """
    sid = request.sid
    if sid in clients:
        emit('pty-output', {'output': '\n[PTY already running]\n'})
        return

    # create pty
    try:
        master_fd, slave_fd = pty.openpty()
    except Exception as e:
        emit('pty-output', {'output': f'\n[failed to open pty: {e}]\n'})
        return

    # set size if provided
    rows = int(data.get('rows', 24))
    cols = int(data.get('cols', 80))
    try:
        set_pty_size(master_fd, rows, cols)
    except Exception:
        pass

    # spawn shell
    shell = os.environ.get('SHELL', '/bin/bash')
    try:
        # start subprocess attached to slave fd
        proc = subprocess.Popen([shell], stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, close_fds=True)
    except Exception as e:
        emit('pty-output', {'output': f'\n[failed to spawn shell: {e}]\n'})
        os.close(master_fd)
        try:
            os.close(slave_fd)
        except Exception:
            pass
        return

    # close slave fd in parent
    try:
        os.close(slave_fd)
    except Exception:
        pass

    # start reading thread
    t = threading.Thread(target=read_and_forward, args=(sid, master_fd), daemon=True)
    clients[sid] = {'master_fd': master_fd, 'proc': proc, 'thread': t}
    t.start()
    emit('pty-output', {'output': f'\n[PTY started: shell {shell}]\n'})

@socketio.on('resize')
def on_resize(data):
    sid = request.sid
    c = clients.get(sid)
    if not c:
        return
    rows = int(data.get('rows', 24))
    cols = int(data.get('cols', 80))
    try:
        set_pty_size(c['master_fd'], rows, cols)
    except Exception:
        pass

@socketio.on('pty-input')
def pty_input(data):
    sid = request.sid
    c = clients.get(sid)
    if not c:
        emit('pty-output', {'output': '\n[no PTY session]\n'})
        return
    s = data.get('input', '')
    try:
        os.write(c['master_fd'], s.encode())
    except Exception as e:
        emit('pty-output', {'output': f'\n[write error: {e}]\n'})

@socketio.on('disconnect')
def ws_disconnect():
    sid = request.sid
    # cleanup
    entry = clients.pop(sid, None)
    if entry:
        try:
            os.close(entry['master_fd'])
        except Exception:
            pass
        try:
            entry['proc'].terminate()
        except Exception:
            pass

if __name__ == '__main__':
    # For local debug (not needed on Render)
    socketio.run(app, host='0.0.0.0', port=PORT)
