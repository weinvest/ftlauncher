import os
import sys
import pwd
import json
import errno
import logging
import signal
import ps_utils
import traceback
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

def set_environ(dir):
    ld_library_path= 'LD_LIBRARY_PATH'
    if ld_library_path in os.environ:
        os.environ[ld_library_path] += ':'+ dir
    else:
        boost_lib = os.path.join(os.environ['BOOST_ROOT'], 'lib')
        hdf5_lib = os.path.join(os.environ['HDF5_ROOT'], 'lib')
        os.environ[ld_library_path] = ':'.join([dir, '/usr/local/lib', '/usr/lib', boost_lib, hdf5_lib])  

@decorator
def set_working_dir(f, self):
    try:
        oldcwd = os.getcwd()
        oldusr = os.geteuid()
        oldgrp = os.getegid()
        oldenv = os.environ['LD_LIBRARY_PATH'] if 'LD_LIBRARY_PATH' in os.environ else ''
        curgid = -1
        os.chdir(self.work_dir)
        work_usr = pwd.getpwnam(self.user)
        curgid = work_usr.pw_gid
        logging.info('change2 work_dir:%s, user:%s, gid:%d', self.work_dir, self.user, curgid)
        #os.seteuid(work_usr.pw_uid)
        #os.setegid(work_usr.pw_gid)
        #set_environ(self.work_dir)
    except Exception as e:
        result = [CommandStatus('chusr', -1, str(e))]
        logging.error('change2 (dir:%s, usr:%d, gid:%s)=>(dir:%s, usr:%s, gid:%s), exception:%s'
                , oldcwd, oldusr, oldgrp
                , self.work_dir, self.user, curgid
                , str(e))
    else:
        result = f(self)
    finally:
        logging.info('restore work_dir:%s, user:%d, gid:%s', oldcwd, oldusr, oldgrp)
        os.chdir(oldcwd)
        #os.seteuid(oldusr)
        #os.setegid(oldgrp)
        os.environ['LD_LIBRARY_PATH'] = oldenv
    return result

class Launcher(object):
    def __init__(self, user, name, home_dir,  work_dir, out_dir, dconn):
        self.user = user
        self.name = name
        self.home_dir = home_dir
        self.work_dir = self.normalize_path(work_dir)
        self.out_dir = self.normalize_path(out_dir) if out_dir is not None else self.work_dir
        self.dconn = dconn
        
        self.dependences = []
        self.dependence_names = []
        self.is_resoloved = False
        self.pid_file_name = '/tmp/.{0}.pid'.format(self.name)
        self.is_help = False
        self.dep_idx = -1
    
    def sort_dependences(self):
        self.dependences = sorted(self.dependences, key=lambda l : l.dep_idx)

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
        if not self.is_help:
            if -1 == self.start_cmd.find('-n'):
                self.start_cmd += ' -n ' + self.name if 0 != len(self.start_cmd) else ''
                self.cmd_user = self.name
            else:
                cmds = self.start_cmd.split()
                idx = cmds.index('-n')
                self.cmd_user = cmds[idx+1]        
        else:
            self.cmd_user = self.user
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
                
    def run_cmd(self, cmd, ignore_error=False, timeout=15, auto_work_dir=True):
        if cmd is None or 0 == len(cmd):
            return CommandStatus('', 0, 'no command execed')
  
        import tempfile
        out = tempfile.TemporaryFile(mode='w+')
        msg = ''
        try:
            args = cmd.split()
            if auto_work_dir:
                work_dir = os.path.dirname(args[0])
                work_dir = work_dir if 0 != len(work_dir) else self.work_dir
            else:
                work_dir = self.work_dir

            #set_environ(work_dir)
            logging.info(f'exec cmd:{cmd}, cwd:{work_dir}')
            p = subprocess.Popen(['su', self.user, '-lc', f'cd {work_dir} && {cmd}'],
                stdout=out, stderr=out, cwd=work_dir, shell=False,
                env=os.environ, close_fds=True)
            p.wait(timeout=timeout)
            retcode = p.returncode
        except Exception as e:
            logging.error(f'run command exception:{cmd}, detail:{str(e)}')
            traceback.print_exc(file=sys.stdout)
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
        
    def run_as_daemon(self, cmd, ignore_error, timeout=1.0):
        self.dconn.send([cmd, self.user, self.work_dir, self.out_dir, self.name, timeout])
        retcode, msg = self.dconn.recv()
        if ignore_error or 0 == retcode:
            return CommandStatus(cmd, retcode, msg)
        else:
            raise RuntimeError(CommandStatus(cmd, retcode, msg))

    @set_working_dir        
    def do_start(self):
        result=[]
        try:
            cur_cmd = 'get_pid'
            pid = ps_utils.get_pid(self.pid_file_name)
            if 0 != pid:
                return [CommandStatus(self.start_cmd, -1, 'already started,pid={0}'.format(pid))]

            if not self.is_resoloved:
                return [CommandStatus(self.start_cmd, -1, 'unresoloved')]

            cur_cmd = self.pre_start_cmd
            if cur_cmd is not None and 0 != len(cur_cmd):
                pre_result = self.run_cmd(self.pre_start_cmd, self.ignore_pre_start_error)
                result.append(pre_result)

            cur_cmd = self.start_cmd
            if cur_cmd is not None and 0 != len(cur_cmd):
                if self.is_help:
                    cmd_result = self.run_cmd(cur_cmd, False, auto_work_dir=False)
                else:
                    cmd_result = self.run_as_daemon(self.start_cmd, False)
                result.append(cmd_result)

            cur_cmd = self.post_start_cmd
            if cur_cmd is not None and 0 != len(cur_cmd):
                post_result = self.run_cmd(self.post_start_cmd, self.ignore_post_start_error)
                result.append(post_result)
            return result
        except RuntimeError as e:
            logging.error(f'start RuntimeError:{cur_cmd}')
            traceback.print_exc(file=sys.stdout)
            result.append(e.args[0])
            return result
        except Exception as e:
            logging.error(f'start Exception:{cur_cmd}')
            traceback.print_exc(file=sys.stdout)
            result.append(CommandStatus(cur_cmd, -1,  str(e)))
            return result
            
    @set_working_dir     
    def do_stop(self):
        result = []
        try:
            cur_cmd = self.pre_stop_cmd
            if cur_cmd is not None and 0 != len(cur_cmd):
                result.append(self.run_cmd(self.pre_stop_cmd, self.ignore_pre_stop_error))

            cur_cmd = self.stop_cmd
            if cur_cmd is not None and 0 != len(cur_cmd):
                result.append(self.run_cmd(self.stop_cmd))

            cur_cmd = self.post_stop_cmd
            if cur_cmd is not None and 0 != len(cur_cmd):
                result.append(self.run_cmd(self.post_stop_cmd, self.ignore_post_stop_error))
        except RuntimeError as e:
            logging.error(f'stop RuntimeError:{cur_cmd}')
            traceback.print_exc(file=sys.stdout)
            result.append(e.args[0])
        except Exception as e:
            logging.error(f'stop Exception:{cur_cmd}')
            traceback.print_exc(file=sys.stdout)
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
            logging.error(f'status RuntimeError:{cur_cmd}')
            traceback.print_exc(file=sys.stdout)
            result.append(e.args[0])
        except Exception as e:
            logging.error(f'status Exception:{cur_cmd}')
            traceback.print_exc(file=sys.stdout)
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
        
