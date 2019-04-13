#!/usr/bin/env python
import socketserver
import loader
import sys
import time
class LauncherServer(socketserver.StreamRequestHandler):
    def setup(self):
        self.usage = ['usage:'
                      , 'start process_name [waittime]'
                      , 'stop process_name stop_dep?'
                      , 'status process_name collect_dep?'
                      , 'restart process_name restart_dep?'
                      , 'ls [user]']
        self.usage = '\n    '.join(self.usage)

        super(LauncherServer,  self).setup()
        self.loader = loader.Loader()
        self.load()
        
    def load(self):
        self.last_load_time = time.time()
        self.loader.load()
        self.loader.resolve()
        
    def handle(self):
        elpased = time.time()-self.last_load_time
        if elpased > 60:
            self.load()
            
        commands = self.rfile.readline().strip().decode()
        commands = commands.split()
        if 0 == len(commands):
            self.wfile.write(self.usage)
        else:
            if 'ls' == commands[0]:
                user = None if 1 == len(commands) else commands[1]
                result = self.loader.list(user)
                result = '\n'.join(result)
            else:
                if 1 == len(commands):
                    result = self.usage
                else:
                    process_name = commands[1]
                    user, process_name = self.loader.split_launcher_name(process_name)
                    launcher = self.loader.get_launcher(process_name, user)
                    if launcher is None:
                        result = 'no launcher named {0}'.format(process_name)
                    else:
                        op = commands[0]
                        if op == 'start':
                            waittime = None if 2==len(commands) else float(commands[2])
                            result = launcher.do_start(waittime)
                        else:
                            do_4_dep = None if 2==len(commands) else bool(commands[1])
                            op_fun = getattr(launcher, 'do_{0}'.format(op), launcher.do_unknown)
                            result = op_fun(do_4_dep)
                        result = launcher.format_result(result)
            
            result += '\n'    
            result = result.encode('utf-8')
            #print(type(result))
            self.wfile.write(result)

        
if __name__ == '__main__':
    if 3 != len(sys.argv):
        print('usage:ftlauncher host port')
        sys.exit(-1)
    
    host = sys.argv[1]
    port = int(sys.argv[2])
    with socketserver.TCPServer((host, port), LauncherServer) as server:
        # Activate the server; this will keep running until you
        # interrupt the program with Ctrl-C
        server.serve_forever()
        
