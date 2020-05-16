import os
import socketserver
import loader
import sys
import time
import logging
import dlauncher
from multiprocessing import Process, Pipe
class LauncherServer(socketserver.StreamRequestHandler):
    def __init__(self, *args, **kargs):
        super(LauncherServer, self).__init__(*args, **kargs)

    def setup(self):
        self.usage = ['usage:'
                      , 'start process_name [waittime]'
                      , 'stop process_name stop_dep?'
                      , 'status process_name collect_dep?'
                      , 'restart process_name restart_dep?'
                      , 'ls [user]']
        self.usage = '\n    '.join(self.usage)

        super(LauncherServer,  self).setup()
        self.loader = loader.Loader(self.server.dconn)
        self.load()
        
    def load(self):
        logging.info('start to load configures')
        self.last_load_time = time.time()
        self.loader.load_user('root', '/root', '/root')
        self.loader.load('/home')
        self.loader.resolve()
        
    def handle(self):
        # elpased = time.time()-self.last_load_time
        # if elpased > 60:
        #     self.load()
            
        commands = self.rfile.readline().strip().decode()
        commands = commands.split()
        if 0 == len(commands):
            self.wfile.write(self.usage)
        else:
            if commands[0] in ['ls', 'list']:
                user = None if 1 == len(commands) else commands[1]
                result = self.loader.list(user)
                result = '\n'.join(result)
            else:
                result = ''
                if 1 == len(commands):
                    result = self.usage
                else:
                    try:
                        process_name = commands[1]
                        user, process_name = self.loader.split_launcher_name(process_name)
                        launcher = self.loader.get_launcher(process_name, user)
                        #print(os.getcwd())
                        if launcher is None:
                            result = 'no launcher named {0}'.format(process_name)
                        else:
                            op = commands[0]
                            do_4_dep = False if 2==len(commands) else bool(commands[2])
                            result = []
                            if do_4_dep:
                                for dep in launcher.dependences:
                                    dep_fun = getattr(dep, 'do_{0}'.format(op), dep.do_unknown)
                                    result.extend(dep_fun())

                            op_fun = getattr(launcher, 'do_{0}'.format(op), launcher.do_unknown)
                            result.extend(op_fun())
                            result = launcher.format_result(result)
                    except Exception as e:
                        result += str(e)
                        logging.error(f'main exception:{str(e)}')
            
            #result += '\n'    
            result = result.encode('utf-8')
            #print(type(result))
            self.wfile.write(result)

        
if __name__ == '__main__':
    if 3 != len(sys.argv):
        print('usage:ftlauncher host port')
        sys.exit(-1)
    parent_conn, child_conn = Pipe()
    dprocess = Process(target=dlauncher.run, args=(child_conn,))
    dprocess.start()

    host = sys.argv[1]
    port = int(sys.argv[2])
    logging.basicConfig(level = logging.DEBUG)

    with socketserver.TCPServer((host, port), LauncherServer) as server:
        # Activate the server; this will keep running until you
        # interrupt the program with Ctrl-C
        server.dconn = parent_conn
        server.allow_reuse_address = True
        server.serve_forever()
        
