import os
import sys
import json
import signal
import ps_utils
import subprocess
from decorator import decorator

class CommandStatus(object):
    def __init__(self, cmd, retcode, msg):
        self.command=str(cmd)
        self.retcode=retcode
        self.message= str(msg)
        
    def __str__(self):
        return json.dumps(self,  cls=CommandStatusEncoder)
    
class CommandStatusEncoder(json.JSONEncoder):    
    def default(self, obj):
        if isinstance(obj, CommandStatus):
            return {'command': obj.command
                , 'retcode': obj.retcode
                , 'message': obj.message}
                
        return json.JSONEncoder.default(self, obj)
    
class Launcher(object):
    def __init__(self, user, name, home_dir,  work_dir):
        self.user = user
        self.name = name
        self.home_dir = home_dir
        self.work_dir = self.normalize_path(work_dir)
        
        self.dependences = []
        self.dependence_names = []
        self.is_resoloved = False
        self.pid_file_name = '/tmp/.{0}.pid'.format(self.name)
    
    def normalize_path(self, p): 
        if p is None:
            return None
            
        p1 = p.replace('~',  self.home_dir) 
        return p1 
        
    def set_start_command(self
        , cmd
        , pre_start_cmd=None
        , post_start_cmd=None
        , ignore_pre_error=False
        , ignore_post_error=False):
        self.start_cmd = self.normalize_path(cmd)
        self.pre_start_cmd = self.normalize_path(pre_start_cmd)
        self.post_start_cmd = self.normalize_path(post_start_cmd)
        self.ignore_pre_start_error = ignore_pre_error
        self.ignore_post_start_error = ignore_post_error
    
    def set_stop_command(self
        , cmd
        , pre_stop_cmd=None
        , post_stop_cmd=None
        , ignore_pre_error=False
        , ignore_post_error=False):
        self.stop_cmd = self.normalize_path(cmd)
        self.pre_stop_cmd = self.normalize_path(pre_stop_cmd)
        self.post_stop_cmd = self.normalize_path(post_stop_cmd)
        self.ignore_pre_stop_error = ignore_pre_error
        self.ignore_post_stop_error = ignore_post_error
    
    def set_status_command(self
        , cmd):
        self.status_cmd = self.normalize_path(cmd)
    
    def add_dependence(self, launcher):
        self.dependences.append(launcher)
    
    def run_cmd(self, cmd, ignore_error=False):
        if cmd is None:
            return None
  
        import tempfile
        out = tempfile.TemporaryFile(mode='w+')
        msg = ''
        try:
            args = cmd.split()
            work_dir = os.path.dirname(args[0])
            work_dir = work_dir if 0 != len(work_dir) else self.work_dir
            ld_library_path= 'LD_LIBRARY_PATH'
            if ld_library_path in os.environ:
                os.environ[ld_library_path] += ':'+work_dir
            else:
                os.environ[ld_library_path] = ':'.join([work_dir, '/usr/local/lib', '/usr/lib'])
                
            p = subprocess.Popen(cmd, stdout=out, stderr=out, cwd=self.work_dir, shell=True,  env=os.environ)
            retcode = p.wait(timeout=5)
        except Exception as e:
            msg = str(e)
            retcode = -1
            if not ignore_error:
                raise 
               
        out.seek(0)
        msg = [str(s) for s in out.readlines()]
        if 0 == len(msg):
            msg = 'on output'
        else:
            msg = ''.join(msg)
            
        cmd_status = CommandStatus(cmd, retcode, msg)
        if 0 != retcode and not ignore_error:
            raise RuntimeError(cmd_status)
        return cmd_status
        
    def get_pid(self):
        if os.path.exists( self.pid_file_name):
            try:
                f = open( self.pid_file_name)
                pid = int(f.read())
            except ValueError:
                return 0
            finally:
                f.close()
            try:
                os.kill(pid, 0)
            except OSError as why:
                if why[0] == os.errno.ESRCH:
                    # The pid doesnt exists.
                    os.remove(self.pid_file_name)
                return 0
            else:
                return pid
        return 0
    
    def run_as_daemon(self, cmd, timeout=1.0):
        c_pid = os.fork()
        if 0 != c_pid:
            retcode = ps_utils.wait_pid(c_pid, 3600.0*timeout)
            try:
                out_file_name = os.path.join(self.work_dir, 'stdout.txt')
                f = open(out_file_name, 'r')
                msg = [str(s) for s in f.readlines()]
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
        
        #write pid
        try:
            f = open(self.pid_file_name,'wb')
            f.write(str(os.getpid()))
        finally:
            f.close()
    
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
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
    
    @decorator
    def set_working_dir(f, self, pa):
        try:
            oldcwd = os.getcwd()
            os.chdir(self.work_dir)
            result = f(self, pa)
        finally:
            os.chdir(oldcwd)
        return result

    @set_working_dir        
    def do_start(self, timeout):
        result=[]
        try:
            pid = self.get_pid()
            if 0 != pid:
                return [CommandStatus(self.start_cmd, -1, 'already started,pid={0}'.format(pid))]

            if not self.is_resoloved:
                return [CommandStatus(self.start_cmd, -1, 'unresoloved')]
                
            for dep_launcher in self.dependences:
                result.extend(dep_launcher.do_start())
            cur_cmd = self.pre_start_cmd
            result.append(self.run_cmd( self.pre_start_cmd, self.ignore_pre_start_error))
            cur_cmd = self.start_cmd
            result.append(self.run_as_daemon(self.start_cmd))
            cur_cmd = self.post_start_cmd
            result.append(self.run_cmd(self.post_start_cmd, self.ignore_post_start_error))
        except RuntimeError as e:
            result.extend(e.args[0])
        except Exception as e:
            result.append(CommandStatus(cur_cmd, -1,  str(e)))
        finally:
            return result
            
    @set_working_dir     
    def do_stop(self, stop_dependences = False):
        result = []
        try:
            cur_cmd = self.pre_stop_cmd
            result.append(self.run_cmd(self.pre_stop_cmd, self.ignore_pre_stop_error))
            cur_cmd = self.stop_cmd
            result.append(self.run_cmd(self.stop_cmd))
            cur_cmd = self.post_stop_cmd
            result.append(self.run_cmd(self.post_stop_cmd, self.ignore_post_stop_error))
            
            if stop_dependences:
                for dep_launcher in self.dependences:
                    result.extend(dep_launcher.do_stop(stop_dependences))
        except RuntimeError as e:
            result.extend(e.args[0])
        except Exception as e:
            result.append(CommandStatus(cur_cmd, -1,  str(e)))            
        finally:
            return result
            
    @set_working_dir         
    def do_restart(self, restart_dependences = False):
        stop_result = self.do_stop(restart_dependences)
        start_result = self.do_start()
        result = stop_result
        result.extend(start_result)
        return result
    
    @set_working_dir     
    def do_status(self, collect_dependences = False):
        result = []
        try:
            cur_cmd=self.status_cmd
            status_result = self.run_cmd(self.status_cmd)
            result.append(status_result)
            if collect_dependences:
                for dep_launcher in self.dependences:
                    result.extend(dep_launcher.do_status(collect_dependences))
                    
        except RuntimeError as e:
            result.extend(e.args[0])
        except Exception as e:
            result.append(CommandStatus(cur_cmd, -1,  str(e)))
        finally:
            return result
    
    def do_unknown(self, do_4_dep = False):
        return [CommandStatus('unknown', -1, 'unknown op')]
    
    def format_result(self, result):
        js_result = [str(i) for i in result]
        return '['+'\n'.join(js_result)+']'
        