"""Resilient auth: file token → Chrome DevTools → fail gracefully."""
import json, os, time, socket, base64, struct
import urllib.request

TOKEN_FILE = "/tmp/astar_token.txt"

def get_token():
    """Get API token. Try file first, then Chrome DevTools."""
    
    # 1. Try saved token file
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            token = f.read().strip()
        if token and len(token) > 50:
            # Verify it still works
            try:
                req = urllib.request.Request(
                    "https://api.ainm.no/astar-island/rounds",
                    headers={"Authorization": f"Bearer {token}"}
                )
                urllib.request.urlopen(req, timeout=5)
                return token
            except:
                pass  # Token expired, try Chrome
    
    # 2. Try Chrome DevTools
    try:
        tabs = json.loads(urllib.request.urlopen("http://localhost:9222/json/list", timeout=3).read())
        if not tabs:
            return None
        tab_id = tabs[0]["id"]
        
        s = socket.socket(); s.connect(("localhost", 9222))
        key = base64.b64encode(os.urandom(16)).decode()
        s.send((f"GET /devtools/page/{tab_id} HTTP/1.1\r\nHost: localhost:9222\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp: resp += s.recv(4096)
        
        def ws_send(sock, msg):
            data = msg.encode(); mask = os.urandom(4); length = len(data)
            frame = bytearray([0x81, 0x80 | (length if length < 126 else 126)])
            if length >= 126: frame += struct.pack(">H", length)
            frame += mask + bytes(b ^ mask[i%4] for i,b in enumerate(data))
            sock.send(bytes(frame))
        
        def ws_recv(sock, timeout=2):
            sock.settimeout(timeout); data = b""
            try:
                while True:
                    chunk = sock.recv(65536)
                    if not chunk: break
                    data += chunk
            except: pass
            if len(data) < 2: return ""
            length = data[1] & 0x7f; offset = 2
            if length == 126: length = struct.unpack(">H", data[2:4])[0]; offset = 4
            elif length == 127: length = struct.unpack(">Q", data[2:10])[0]; offset = 10
            return data[offset:offset+length].decode(errors='replace')
        
        ws_send(s, json.dumps({"id": 1, "method": "Network.enable"}))
        time.sleep(0.2); ws_recv(s, 0.3)
        ws_send(s, json.dumps({"id": 2, "method": "Network.getAllCookies"}))
        time.sleep(0.5)
        cookies = json.loads(ws_recv(s, 1)).get("result", {}).get("cookies", [])
        s.close()
        
        token = next((c["value"] for c in cookies if c["name"] == "access_token"), None)
        
        if token:
            # Save for next time
            with open(TOKEN_FILE, "w") as f:
                f.write(token)
            return token
    except:
        pass
    
    return None

if __name__ == "__main__":
    t = get_token()
    if t:
        print(f"Token: {t[:20]}... ({len(t)} chars)")
    else:
        print("NO TOKEN AVAILABLE")
