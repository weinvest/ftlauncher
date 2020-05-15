import os
import sys
import pwd
import time
import signal
import ps_utils
import daemon
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
    pid_file_name = f'/tmp/{name}.pid'
    exe_dir, exe_path, exe_name = split_exe_info(cmd.split()[0])

    child_pid = os.fork()
    if 0 == child_pid:
        try:
            os.close(ctx.conn.fileno())
            #print(os.environ['LD_LIBRARY_PATH'])
            daemon.daemonize(pid_file_name)
            signal.signal(signal.SIGHUP, signal.SIG_IGN)

            os.chdir(exe_dir)

            stdout_file = f'{out_dir}/{name}.{os.getpid()}'

            redirect(stdout_file, 1, os.O_RDWR| os.O_CREAT)
            redirect(stdout_file, 2, os.O_RDWR | os.O_CREAT)

            sys.stdout = open(stdout_file,'w')
            sys.stderr = open(stdout_file,'w')

            args = cmd.split()
            envs = {'LD_LIBRARY_PATH': os.environ["LD_LIBRARY_PATH"]}

            f = open('/tmp/alpha.out', 'w')
            f.write(f'{exe_path}\n')
            f.write(f'{args}\n')
            f.write(f'{envs}\n')
            f.close()

            os.execve(exe_path, args, env=envs)

        except Exception as ex:
            pid = child_pid if 0 != child_pid else os.getpid()
            sys.stdout.write(f'{datetime.datetime.now().isoformat()} {exe_name} exception, pid is: {pid}, detail: {ex}\n')
            sys.stdout.flush()
            if os.path.exists(pid_file_name):
                os.remove(pid_file_name)
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
                msg = [str(s) for s in f.readlines()]
            except Exception as e:
                retcode=2
                msg = str(e)

            return [retcode, msg]
        else:
            return [3, "can't read pid from pidfile"]

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


