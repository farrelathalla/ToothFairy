"""
labmcp.py - tiny client for the official Blender Lab MCP addon socket.

Protocol (from lab_blender_org/mcp/mcp_to_blender_server.py):
  * connect to localhost:9876
  * send null-byte-delimited JSON: {"type":"execute","code":"<py>"}\0
  * the code must assign a dict to `result`
  * read null-byte-delimited JSON response: {"status":"ok","result":{...}}\0

Usage:
  python blender/labmcp.py ping
  python blender/labmcp.py run path/to/script_body.py   # body must set result={...}
"""
import socket
import json
import sys

HOST, PORT = "localhost", 9876


def execute(code, timeout=180):
    s = socket.socket()
    s.settimeout(timeout)
    s.connect((HOST, PORT))
    s.sendall(json.dumps({"type": "execute", "code": code, "strict_json": False}).encode() + b"\x00")
    buf = b""
    while b"\x00" not in buf:
        ch = s.recv(65536)
        if not ch:
            break
        buf += ch
    s.close()
    payload = buf.split(b"\x00", 1)[0].decode(errors="replace")
    return json.loads(payload) if payload else {"status": "empty"}


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "run":
        body = open(sys.argv[2], encoding="utf-8").read()
        print(json.dumps(execute(body), indent=2))
    else:
        code = "import bpy\nresult = {'version': bpy.app.version_string, 'objects': len(bpy.data.objects)}"
        print(json.dumps(execute(code, timeout=20), indent=2))
