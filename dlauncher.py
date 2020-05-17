import os
import sys
import pwd
import time
import signal
import ps_utils
import traceback
import datetime
from launcher import set_working_dir
def split_exe_info(executale):
    exe_dir = executale
    exe_path = executale
    if os.path.isfile(exe_path):
        exe_dir = os.path.dirname(exe_dir)
    else:
        raise Exception(f"can't find {executale} in {os.getcwd()}")

    return (exe_dir, exe_path, os.path.basename(exe_path))

def redirect(file_name, fid, option):
    f = os.open(file_name, option)
    os.dup2(f, fid)
    os.close(f)

class EmptyCls(object):
    pass

@set_working_dir
def run_daemon(ctx):
    cmd, out_dir, name, timeout = ctx.req
    pid_file_name = f'/tmp/.{name}.pid'

    child_pid = os.fork()
    if 0 == child_pid:
        try:
            os.close(ctx.conn.fileno())
            ps_utils.daemonize(pid_file_name)
            signal.signal(signal.SIGHUP, signal.SIG_IGN)

            stdout_file = f'{out_dir}/{name}.{os.getpid()}'

            redirect(stdout_file, 1, os.O_RDWR| os.O_CREAT)
            redirect(stdout_file, 2, os.O_RDWR | os.O_CREAT)

            sys.stdout = open(stdout_file,'w')
            sys.stderr = open(stdout_file,'w')
            
            work_usr = pwd.getpwnam(ctx.user)
            os.chown(stdout_file, work_usr.pw_uid, work_usr.pw_gid)

            args = ['su', ctx.user, '-lc', f'cd {ctx.work_dir} && '+cmd]
            envs = {'LD_LIBRARY_PATH': os.environ["LD_LIBRARY_PATH"]}

            os.execvpe(args[0], args, env=envs)

        except Exception:
            pid = child_pid if 0 != child_pid else os.getpid()
            sys.stdout.write(f'{datetime.datetime.now().isoformat()} run {cmd} exception, pid is: {pid}, detail:\n')
            traceback.print_exc(file=sys.stdout)
            sys.stdout.flush()
        finally:
            sys.exit(0)
    else:
        time.sleep(timeout)
        pid = ps_utils.get_pid(pid_file_name)
        if 0 != pid:
            retcode = 0
            try:
                out_file_name = os.path.join(out_dir, f'{out_dir}/{name}.{pid}')
                f = open(out_file_name, 'r')
                msg = ''.join([str(s) for s in f.readlines()])
            except Exception as e:
                retcode=2
                msg = str(e)

            return [retcode, msg]
        else:
            return [3, f"can't read pid from {pid_file_name}"]

def run(conn):
    while True:
        request = conn.recv()
        cmd, user, work_dir, out_dir, name, timeout = request

        ctx = EmptyCls()
        ctx.req = (cmd, out_dir, name, timeout)
        ctx.user = user
        ctx.work_dir = work_dir
        ctx.conn = conn
        try:
            ret = run_daemon(ctx)
        except Exception as e:
            ret = [1, str(e)]
        conn.send(ret)


