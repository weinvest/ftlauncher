import os
import sys
import pwd
import json
import errno
import logging
import signal
import ps_utils
import daemon
import datetime
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
        return p1.strip() 
        
    def set_start_command(self
        , cmd
        , pre_start_cmd=None
        , post_start_cmd=None
        , ignore_pre_error=False
        , ignore_post_error=False):
        self.start_cmd = self.normalize_path(cmd)
        if -1 == self.start_cmd.find('-n'):
            self.start_cmd += ' -n ' + self.name
            self.cmd_user = self.name
        else:
            cmds = self.start_cmd.split()
            idx = cmds.index('-n')
            self.cmd_user = cmds[idx+1]
        
        #if not self.start_cmd.startswith('nohup'):
        #    self.start_cmd = 'nohup {0} '.format(self.start_cmd)
        
        #if '>' not in self.start_cmd:
        #self.start_cmd += ' >stdout.txt'
            
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
    
    def set_environ(self, dir):
        ld_library_path= 'LD_LIBRARY_PATH'
        if ld_library_path in os.environ:
            os.environ[ld_library_path] += ':'+ dir
        else:
            boost_lib = os.path.join(os.environ['BOOST_ROOT'], 'lib')
            hdf5_lib = os.path.join(os.environ['HDF5_ROOT'], 'lib')
            os.environ[ld_library_path] = ':'.join([dir, '/usr/local/lib', '/usr/lib', boost_lib, hdf5_lib])    
            
    def run_cmd(self, cmd, ignore_error=False, timeout=5):
        if cmd is None:
            return CommandStatus('', 0, 'no command execed')
  
        import tempfile
        out = tempfile.TemporaryFile(mode='w+')
        msg = ''
        try:
            args = cmd.split()
            work_dir = os.path.dirname(args[0])
            work_dir = work_dir if 0 != len(work_dir) else self.work_dir
            self.set_environ(work_dir)
                
            p = subprocess.Popen(cmd, stdout=out, stderr=out, cwd=work_dir, shell=True,  env=os.environ, close_fds=True)
            p.wait(timeout=timeout)
            retcode = p.returncode
        except Exception as e:
            logging.error('run command exception:%s', str(e))
            msg = str(e)
            retcode = -1
            if not ignore_error:
                raise 
               
        out.seek(0)
        msg = [str(s) for s in out.readlines()]
        if 0 != len(msg):
            msg = ''.join(msg)
            
        cmd_status = CommandStatus(cmd, retcode, msg)
        return cmd_status
        
    def get_pid(self):
        if os.path.exists( self.pid_file_name):
            try:
                f = open(self.pid_file_name, 'r')
                pid = int(f.read())
            except Exception:
                return 0
            finally:
                f.close()
                
            try:
                os.kill(pid, 0)
            except OSError as why:
                if why.errno == errno.ESRCH:
                    # The pid doesnt exists.
                    os.remove(self.pid_file_name)
                return 0
            except Exception as e:
                print(str(e))
                return 0
            else:
                return pid
        return 0

    def split_exe_info(self, executale):
        exe_dir = executale
        exe_path = executale
        if os.path.isfile(exe_path):
            exe_dir = os.path.dirname(exe_dir)
        else:
            raise Exception(executale + ' must be a executable file')
        return (exe_dir, exe_path, os.path.basename(exe_path))

    def redirect(self, file_name, fid, option):
        f = os.open(file_name, option)
        os.dup2(f, fid)
        os.close(f)

    def run_as_daemon(self, cmd, timeout=1.0):
        c_pid = os.fork()
        if 0 != c_pid:
            retcode = ps_utils.wait_pid(c_pid, 3600.0*timeout)
            try:
                out_file_name = os.path.join(self.work_dir, 'stdout.txt')
                f = open(out_file_name, 'r')
                #msg = '\n'.join([str(s) for s in f.readlines()])
                msg = [str(s) for s in f.readlines()]
            except Exception as e:
                retcode=2
                msg = str(e)

            return CommandStatus(cmd, retcode, msg)
        
        #close all opened fds except stdin/stdout/stderr
        for fd in range(3, 8192):
            try:
                os.close(fd)
            except:
                pass

        exe_dir, exe_path, exe_name = self.split_exe_info(cmd.split()[0])
        pid_file_name = '/tmp/%s.pid' % exe_name
        try:
            pid_file = open(pid_file_name, 'r')
            daemon.checkPID(pid_file_name)
        except Exception:
            pass

        try:
            daemon.daemonize(pid_file_name)
            signal.signal(signal.SIGHUP, signal.SIG_IGN)

            self.redirect('stdout.txt', 1, os.O_RDWR| os.O_CREAT)
            self.redirect('stdout.txt', 2, os.O_RDWR| os.O_CREAT)
            sys.stdout = sys.stderr = open('stdout.txt','w')

            child_pid = os.fork()
            if 0 == child_pid:
                os.chdir(exe_dir)

                str_pid = str(os.getpid())
                stdin_file = 'stdin.' + str_pid
                stdout_file = 'stdout.' + str_pid
                stderr_file = 'stderr.' + str_pid

                self.redirect(stdin_file, 0, os.O_RDONLY | os.O_CREAT)
                self.redirect(stdout_file, 1, os.O_RDWR| os.O_CREAT)
                self.redirect(stderr_file, 2, os.O_RDWR | os.O_CREAT)

                sys.stdin = open(stdin_file,'r')
                sys.stdout = open(stdout_file,'w')
                sys.stderr = open(stderr_file,'w')

                args = cmd.split()
                self.set_environ(self.work_dir)
                envs={'LD_LIBRARY_PATH': os.environ['LD_LIBRARY_PATH']}
                os.execve(args[0], args, envs)
                os.execv(exe_path, args)
            else:
                sys.stdout.write(f'{datetime.datetime.now().isoformat()} {exe_name} started, pid is: {child_pid}\n')
                result = os.waitpid(child_pid, 0)
                sys.stdout.write(f'{datetime.datetime.now().isoformat()} {exe_name} stopped, pid is: {child_pid}, status: {result[1]}\n')
                sys.stdout.flush()
        except Exception as ex:
            sys.stdout.write(f'{datetime.datetime.now().isoformat()} {exe_name} exception, pid is: {child_pid}, detail: {ex}\n')
            sys.stdout.flush()

            if os.path.exists(pid_file_name):
                os.remove(pid_file_name)

    @decorator
    def set_working_dir(f, self):
        try:
            oldcwd = os.getcwd()
            oldusr = os.geteuid()
            oldgrp = os.getegid()
            curgid = -1
            os.chdir(self.work_dir)
            work_usr = pwd.getpwnam(self.user)
            curgid = work_usr.pw_gid
            logging.info('change2 work_dir:%s, user:%s, gid:%d', self.work_dir, self.user, curgid)
            os.seteuid(work_usr.pw_uid)
            #os.setegid(work_usr.pw_gid)
            self.set_environ(self.work_dir)
            result = f(self)
        except Exception as e:
            result = [CommandStatus('chusr', -1, str(e))]
            logging.error('change2 (dir:%s, usr:%d, gid:%s)=>(dir:%s, usr:%s, gid:%s), exception:%s'
                    , oldcwd, oldusr, oldgrp
                    , self.work_dir, self.user, curgid
                    , str(e))
        finally:
            logging.info('restore work_dir:%s, user:%d, gid:%s', oldcwd, oldusr, oldgrp)
            os.chdir(oldcwd)
            os.seteuid(oldusr)
            #os.setegid(oldgrp)
        return result

    @set_working_dir        
    def do_start(self):
        result=[]
        try:
            cur_cmd = 'get_pid'
            pid = self.get_pid()
            if 0 != pid:
                return [CommandStatus(self.start_cmd, -1, 'already started,pid={0}'.format(pid))]

            if not self.is_resoloved:
                return [CommandStatus(self.start_cmd, -1, 'unresoloved')]

            cur_cmd = self.pre_start_cmd
            result.append(self.run_cmd( self.pre_start_cmd, self.ignore_pre_start_error))
            cur_cmd = self.start_cmd
            result.append(self.run_as_daemon(self.start_cmd))
            cur_cmd = self.post_start_cmd
            result.append(self.run_cmd(self.post_start_cmd, self.ignore_post_start_error))
            return result
        except RuntimeError as e:
            result.append(e.args[0])
            return result
        except Exception as e:
            result.append(CommandStatus(cur_cmd, -1,  str(e)))
            return result
            
    @set_working_dir     
    def do_stop(self):
        result = []
        try:
            cur_cmd = self.pre_stop_cmd
            result.append(self.run_cmd(self.pre_stop_cmd, self.ignore_pre_stop_error))
            cur_cmd = self.stop_cmd
            result.append(self.run_cmd(self.stop_cmd))
            cur_cmd = self.post_stop_cmd
            result.append(self.run_cmd(self.post_stop_cmd, self.ignore_post_stop_error))
        except RuntimeError as e:
            result.append(e.args[0])
        except Exception as e:
            result.append(CommandStatus(cur_cmd, -1,  str(e)))
        finally:
            return result
            
    @set_working_dir         
    def do_restart(self):
        stop_result = self.do_stop()
        start_result = self.do_start()
        result = stop_result
        result.extend(start_result)
        return result
    
    @set_working_dir     
    def do_status(self):
        result = []
        try:
            cur_cmd=self.status_cmd
            status_result = self.run_cmd(self.status_cmd)
            result.append(status_result)
        except RuntimeError as e:
            result.append(e.args[0])
        except Exception as e:
            logging.error('do_status exception:%s', str(e))
            result.append(CommandStatus(cur_cmd, -1,  str(e)))
        finally:
            return result
    
    def do_unknown(self, do_4_dep = False):
        return [CommandStatus('unknown', -1, 'unknown op')]
    
    def format_result(self, result):
        if isinstance(result, list):
            js_result = [str(i) for i in result]
            return '['+',\n'.join(js_result)+']'
        else:
            return result
        
