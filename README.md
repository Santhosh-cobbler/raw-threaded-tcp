# raw-threaded-tcp
# RawShell — Multi-Threaded TCP Command Server

> Zero-framework. Raw sockets. Thread-per-connection concurrency model. Built to understand the OS primitives that every high-level server hides from you.

---

## What This Is

RawShell is a multi-threaded TCP command server written in pure Python using only the standard library — `socket`, `threading`, and `queue`. No Twisted. No asyncio. No FastAPI. Just file descriptors, OS threads, and raw byte streams.

The server exposes an interactive CLI (`turtle>`) that lets you list all connected clients, select one by index, and pipe shell commands to it. The client runs on any machine with Python — including Android phones via Termux — and executes commands in a subprocess, streaming the output back.

This was built and stress-tested with **two Android devices simultaneously connected over a local Wi-Fi network**, both receiving commands concurrently from a single server terminal.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    SERVER (thr_server.py)                  │
│                                                            │
│  ┌──────────────┐      ┌──────────────────────────────┐  │
│  │  Thread #1   │      │  Thread #2                    │  │
│  │              │      │                               │  │
│  │ accept_loop  │      │  turtle> CLI                  │  │
│  │              │      │                               │  │
│  │  s.accept()  │      │  list → all_connections[]     │  │
│  │      ↓       │      │  select N → conn handle       │  │
│  │  append to   │      │  cmd → conn.send(bytes)       │  │
│  │  all_conns[] │      │  response → conn.recv()       │  │
│  └──────────────┘      └──────────────────────────────┘  │
│         │                           │                      │
│         └──────────┬────────────────┘                      │
│                    │                                        │
│              shared state:                                  │
│         all_connections[], all_address[]                    │
└──────────────────────────────────────────────────────────┘
                         │  TCP / Wi-Fi LAN
          ┌──────────────┼──────────────┐
          ↓              ↓              ↓
   ┌────────────┐ ┌────────────┐ ┌────────────┐
   │ Client A   │ │ Client B   │ │ Client N   │
   │ (Android/  │ │ (Android/  │ │ (any host) │
   │  Termux)   │ │  Termux)   │ │            │
   └────────────┘ └────────────┘ └────────────┘
```

**Thread allocation:**
- Thread 1 → `accepting_the_connections()` — blocks on `s.accept()`, appends each new socket to `all_connections`
- Thread 2 → `start_turtle()` — reads from stdin, routes commands to selected connections

**Job queue dispatch:** A `Queue` object maps job IDs to functions. Workers pull from the queue and execute. This is the producer-consumer pattern implemented at the thread level.

---

## OS Primitives: What's Actually Happening

### File Descriptors

Every TCP connection in Linux is represented as a **file descriptor (FD)** — an integer index into the kernel's open-file table for that process. When you call `socket.socket()`, the OS allocates an FD. When you call `s.accept()`, it allocates a *new* FD for the accepted connection. The `conn` objects in `all_connections[]` are Python wrappers around these FDs.

**Implication:** Each unclosed connection holds a kernel resource. If you restart the server without explicitly closing old sockets, those FDs remain allocated until the OS garbage-collects them (TCP TIME_WAIT). This is why `accepting_the_connections()` closes all previous connections on startup:

```python
for c in all_connections:
    c.close()
```

### Thread Allocation

Python threads map to OS-level threads (POSIX `pthreads`). The GIL (Global Interpreter Lock) prevents true parallel CPU execution, but for **I/O-bound work** — which TCP socket operations are — threads release the GIL during blocking calls (`recv`, `send`, `accept`). This is why the thread model works here: Thread 1 blocks on `accept()`, Thread 2 blocks on `input()`, and both wait in the kernel without contending for the GIL.

### State Isolation

`all_connections` and `all_address` are shared mutable lists accessed by both threads. Thread 1 appends to them; Thread 2 reads and deletes from them. This is a **race condition** in the current implementation — a lock is needed for production safety (see Known Issues).

---

## Setup & Reproduction

### Server (your machine)

**Requirements:** Python 3.8+

```bash
git clone https://github.com/YOUR_USERNAME/rawshell.git
cd rawshell
python thr_server.py
```

Find your local IP address:
```bash
# Linux/macOS
ip addr show | grep "inet " | grep -v 127.0.0.1

# Windows
ipconfig | findstr "IPv4"
```

The server binds to `0.0.0.0:9999` and listens for connections.

### Client — Android via Termux

**Step 1: Install Termux** from [F-Droid](https://f-droid.org/en/packages/com.termux/) (not the Play Store version — it's outdated).

**Step 2: Install Python in Termux**
```bash
pkg update && pkg upgrade
pkg install python
```

**Step 3: Transfer or create the client file**
```bash
# Option A: via curl if you have it hosted
curl -O https://raw.githubusercontent.com/YOUR_USERNAME/rawshell/main/thr_client.py

# Option B: type it directly (it's short)
nano thr_client.py
```

**Step 4: Update the server IP in `thr_client.py`**
```python
host = "192.168.X.X"  # Replace with your server's local IP
port = 9999
```

**Step 5: Connect both devices to the same Wi-Fi network, then run:**
```bash
python thr_client.py
```

### Server CLI Usage

```
turtle> list
-----clients-----
0    192.168.31.51    54321
1    192.168.31.52    54322

turtle> select 0
you are connected to: 192.168.31.51
192.168.31.51> whoami
u0_a123
192.168.31.51> pwd
/data/data/com.termux/files/home
192.168.31.51> quit

turtle> select 1
...
```

---

## Known Issues & Thread-Safety Analysis

| Issue | Location | Risk | Fix |
|---|---|---|---|
| Race condition on `all_connections` | `accepting_the_connections()` + `list_connections()` | Medium — concurrent append/delete without lock | Wrap with `threading.Lock()` |
| No socket timeout on accepted connections | `conn.setblocking(1)` | Low — stale connections block forever | Use `conn.settimeout(30)` |
| HTTP response mixed with command flow | `accepting_the_connections()` | Medium — sends HTTP response to first message, breaks non-browser clients | Remove HTTP handling or branch by client type |
| `bind_sockets()` recursive retry | On `socket.error` | High — unbounded recursion on persistent failure | Replace with iterative retry + backoff |
| Client has no reconnect logic | `thr_client.py` | Low — drops silently on disconnect | Add loop with exponential backoff |

**Thread-safety fix (drop-in):**
```python
conn_lock = threading.Lock()

# In accepting_the_connections():
with conn_lock:
    all_connections.append(conn)
    all_address.append(addr)

# In list_connections() and get_target():
with conn_lock:
    # read/delete operations
```

---

## Phase 2 Blueprint: Thread-per-Connection → I/O Multiplexing

### Why the current model breaks at scale

Each connection = 1 OS thread. OS threads are expensive:

- Default stack size: **8MB per thread** on Linux
- Context switch overhead: **1–10 microseconds** per switch
- At 10,000 connections → **80GB RAM** just for thread stacks + scheduler thrashing

### The async alternative: `selectors` (epoll under the hood)

Instead of one thread per connection, a single thread registers all socket FDs with the OS's **I/O readiness notification** mechanism (`epoll` on Linux, `kqueue` on macOS). The OS notifies you when a socket has data ready — you process it, then return to the event loop. Zero blocked threads. Zero wasted stack memory.

```python
import selectors
import socket

sel = selectors.DefaultSelector()  # Uses epoll on Linux automatically

def accept(sock):
    conn, addr = sock.accept()
    conn.setblocking(False)
    sel.register(conn, selectors.EVENT_READ, data=read)

def read(conn):
    data = conn.recv(1024)
    if data:
        conn.send(data)  # echo back, or route to command handler
    else:
        sel.unregister(conn)
        conn.close()

server = socket.socket()
server.bind(('', 9999))
server.listen()
server.setblocking(False)
sel.register(server, selectors.EVENT_READ, data=accept)

while True:
    events = sel.select(timeout=None)  # blocks until ANY socket is ready
    for key, mask in events:
        callback = key.data
        callback(key.fileobj)
```

**What changes structurally:**

| Dimension | Thread-per-Connection (current) | I/O Multiplexing (Phase 2) |
|---|---|---|
| Concurrency model | 1 OS thread per client | 1 event loop, N registered FDs |
| Memory per connection | ~8MB (thread stack) | ~1KB (selector registration) |
| 10,000 connections | ~80GB RAM + GIL contention | ~10MB RAM |
| Latency profile | Low for few connections | Consistent at scale |
| Complexity | Simple, readable | Requires callback/coroutine design |
| Socket leak risk | High (unclosed on crash) | Low (centralized `sel.unregister` + `close`) |

### The `asyncio` path (higher-level)

```python
import asyncio

async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    while True:
        data = await reader.read(1024)
        if not data:
            break
        writer.write(data)
        await writer.drain()
    writer.close()

async def main():
    server = await asyncio.start_server(handle_client, '', 9999)
    async with server:
        await server.serve_forever()

asyncio.run(main())
```

`asyncio` wraps `selectors` behind coroutines. `await reader.read()` suspends the coroutine (not the thread) and yields control back to the event loop — which runs other coroutines while this one waits for data. At 10,000 connections, you have 10,000 suspended coroutines and one running OS thread.

### Migration path from this codebase

1. Replace `all_connections[]` list with an `asyncio`-safe dict: `clients: dict[str, asyncio.StreamWriter]`
2. Port `send_target_command()` to an `async def` coroutine that awaits on `writer.write()` + `reader.read()`
3. Replace the `turtle>` input loop with `asyncio.get_event_loop().run_in_executor()` — keeps the CLI interactive without blocking the event loop
4. Phase out `threading.Thread` entirely; the event loop handles all concurrency

---

## File Structure

```
rawshell/
├── thr_server.py     # Multi-threaded TCP server with CLI
├── thr_client.py     # Lightweight command execution client
└── README.md
```

---

## Strategic Context

This project is the systems foundation for a larger research direction: **multi-agent AI network infrastructure**. The immediate goal is production-grade understanding of the transport layer — raw TCP, socket state management, OS thread allocation — before introducing higher-level abstractions.

The async migration in Phase 2 is not academic. It's the architectural prerequisite for handling 10,000+ simultaneous AI agent connections on a single machine without vertical scaling.
