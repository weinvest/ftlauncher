import os
import sys
import json
import signal
import ps_utils
import subprocess

class CommandStatus(json.JSONEncoder):
    def __init__(self, cmd, retcode, msg):
        self.command=cmd
        self.retcode=retcode
        self.message=msg
    
    def default(self, obj):
        if isinstance(obj, CommandStatus):
            return {'command': self.command
                , 'retcode': self.retcode
                , 'message': self.message}
                
        return json.JSONEncoder.default(self, obj)
    
    def __str__(self):
        return json.dumps(self,  cls=CommandStatus)
    
class Launcher(object):
    def __init__(self, name, work_dir):
        self.name = name
        self.work_dir = work_dir
        self.dependences = []
        self.dependence_names = []
        self.last_update_time = 0
        self.is_resoloved = False
        
    def set_start_command(self
        , cmd
        , pre_start_cmd=None
        , post_start_cmd=None):
        self.start_cmd = cmd
        self.pre_start_cmd = pre_start_cmd
        self.post_start_cmd = post_start_cmd
    
    def set_stop_command(self
        , cmd
        , pre_stop_cmd=None
        , post_stop_cmd=None):
        self.stop_cmd = cmd
        self.pre_stop_cmd = pre_stop_cmd
        self.post_stop_cmd = post_stop_cmd
    
    def set_status_command(self
        , cmd):
        self.status_cmd = cmd
    
    def add_dependence(self, launcher):
        self.dependences.append(launcher)
    
    def run_cmd(self, cmd):
        if cmd is None:
            return None
            
        import tempfile
        out = tempfile.TemporaryFile()
        retcode = subprocess.call(cmd, stdout=out, stderr=out)
        out.rewind()
        msg = out.readall()
        cmd_status = CommandStatus(cmd, retcode, msg)
        if 0 != retcode:
            raise RuntimeError([cmd_status])
        
        return cmd_status
    
    def run_as_daemon(self, cmd, timeout=1.0):
        try:
            pid_file_name = '/tmp/'+self.name+'.pid'
            c_pid = os.fork()
            if 0 != c_pid:
                retcode = ps_utils.wait_pid(c_pid, 3600.0)
                try:
                    out_file_name = os.path.join(self.work_dir, 'stdout.txt')
                    f = open(out_file_name, 'r')
                    msg = f.readall()
                except:
                    retcode=2
                    msg = os.strerror(retcode)
                return CommandStatus(cmd, retcode, msg)
                
            os.setsid()
            cc_pid=os.fork()
            if 0 != cc_pid:   # launch child and...
                try:
                    retcode = ps_utils.wait_pid(cc_pid, timeout)
                except RuntimeError:
                    retcode = -1
                except ps_utils.TimeoutExpired:
                    retcode = 0
                except OSError as oe:
                    retcode = oe.errorno
                return retcode
                
            os.umask(0o22)   # Don't allow others to write
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            os.chdir(self.work_dir)
            for i in range(0, 1024):
                os.close(i)
            
            stdin = os.open('/dev/null', os.O_RDWR)
            outfile = os.open('stdout.txt',os.O_RDWR | os.O_CREAT)
            os.dup2(stdin,0)
            os.dup2(outfile,1)
            os.dup2(outfile,2)

            os.close(stdin)
            os.close(outfile)

            sys.stdin = open('/dev/null','r')
            sys.stdout = open('stdout.txt','w')
            sys.stderr = sys.stdout

            os.umask(0)
            sys.stdout.flush()

            args = cmd.split()
            os.execv(args[0], args)
        except Exception as ex:
            if os.path.exists(pid_file_name):
                os.remove(pid_file_name)
            
    def do_start(self, timeout):
        try:
            if not self.is_resoloved:
                return [CommandStatus(self.start_cmd, -1, 'unresoloved')]
            
            result=[]
            for dep_launcher in self.dependences:
                result.extend(dep_launcher.do_start())
                
            result.append(self.run_cmd(self.pre_start_cmd))
            result.append(self.run_as_daemon(self.start_cmd))
            result.append(self.run_cmd(self.post_start_cmd))
        except RuntimeError as e:
            result.extend(e.args[0])
        finally:
            return result
    
    def do_stop(self, stop_dependences = False):
        result = []
        try:
            result.append(self.run_cmd(self.pre_stop_cmd))
            result.append(self.run_cmd(self.stop_cmd))
            result.append(self.run_cmd(self.post_stop_cmd))
            
            if stop_dependences:
                for dep_launcher in self.dependences:
                    result.extend(dep_launcher.do_stop(stop_dependences))
        except RuntimeError as e:
            result.extend(e.args[0])
            raise RuntimeError(result)
        finally:
            return result
        
    def do_restart(self, restart_dependences = False):
        stop_result = self.do_stop(restart_dependences)
        start_result = self.do_start()
        result = stop_result
        result.extend(start_result)
        return result
    
    def do_status(self, collect_dependences = False):
        result = []
        try:
            result.append(self.run_cmd(self.status_cmd))
            if collect_dependences:
                for dep_launcher in self.dependences:
                    result.extend(dep_launcher.do_status(collect_dependences))
                    
        except RuntimeError as e:
            result.extend(e.args[0])
            raise RuntimeError(result)
        finally:
            return result
