#!/usr/bin/env python3
# Raw WebSocket client transport (no external deps). Python 3.5 safe.
import os, socket, base64, struct, json


def ws_connect(host, port, path):
    s = socket.create_connection((host, port), timeout=15)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    k = base64.b64encode(os.urandom(16)).decode()
    s.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, host, k)).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(65536)
    return s, {"b": buf.split(b"\r\n\r\n", 1)[1]}


def need(s, box, n):
    while len(box["b"]) < n:
        chunk = s.recv(65536)
        if not chunk:
            raise IOError("websocket closed (EOF)")
        box["b"] += chunk


def ws_frame(s, box):
    need(s, box, 2)
    b0 = box["b"][0]; op = b0 & 0x0f; ln = box["b"][1] & 0x7f; idx = 2
    if ln == 126:
        need(s, box, 4); ln = struct.unpack(">H", box["b"][2:4])[0]; idx = 4
    elif ln == 127:
        need(s, box, 10); ln = struct.unpack(">Q", box["b"][2:10])[0]; idx = 10
    need(s, box, idx + ln)
    p = box["b"][idx:idx + ln]; box["b"] = box["b"][idx + ln:]
    return (b0 & 0x80), op, p


def ws_pong(s, payload):
    p = payload[:125]; m = os.urandom(4); ln = len(p)
    md = bytes(bytearray(x ^ m[i % 4] for i, x in enumerate(p)))
    s.sendall(b"\x8a" + bytes(bytearray([0x80 | ln])) + m + md)


def ws_read(s, box):
    data = b""
    while True:
        fin, op, p = ws_frame(s, box)
        if op == 8:
            return None          # close
        if op == 9:
            ws_pong(s, p); continue   # ping -> pong (keepalive)
        if op == 10:
            continue            # pong
        data += p
        if fin:
            try:
                return json.loads(data.decode("utf-8"))
            except Exception:
                data = b""


def ws_send(s, obj):
    d = json.dumps(obj).encode(); m = os.urandom(4)
    md = bytes(bytearray(x ^ m[i % 4] for i, x in enumerate(d))); ln = len(d)
    if ln < 126:
        s.sendall(b"\x81" + bytes(bytearray([0x80 | ln])) + m + md)
    elif ln < 65536:
        s.sendall(b"\x81" + bytes(bytearray([0x80 | 126])) + struct.pack(">H", ln) + m + md)
    else:
        s.sendall(b"\x81" + bytes(bytearray([0x80 | 127])) + struct.pack(">Q", ln) + m + md)
