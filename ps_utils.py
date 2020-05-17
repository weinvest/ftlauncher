import os
import time
import errno


class TimeoutExpired(Exception):
    pass

def pid_exists(pid):
    """Check whether pid exists in the current process table."""
    if pid < 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as e:
        return e.errno == errno.EPERM
    else:
        return True

def get_pid(pid_file_name):
    if os.path.exists( pid_file_name):
        try:
            f = None
            f = open(pid_file_name, 'r')
            pid = int(f.read())
        except Exception:
            return 0
        finally:
            if f is not None:
                f.close()
            
        try:
            os.kill(pid, 0)
        except OSError as why:
            if why.errno == errno.ESRCH:
                # The pid doesnt exists.
                os.remove(pid_file_name)
            return 0
        except Exception as e:
            print(str(e))
            return 0
        else:
            return pid
    return 0

def wait_pid(pid, timeout=None):
    """Wait for process with pid 'pid' to terminate and return its
    exit status code as an integer.

    If pid is not a children of os.getpid() (current process) just
    waits until the process disappears and return None.

    If pid does not exist at all return None immediately.

    Raise TimeoutExpired on timeout expired (if specified).
    """
    def check_timeout(delay):
        if timeout is not None:
            if time.time() >= stop_at:
                raise TimeoutExpired
        time.sleep(delay)
        return min(delay * 2, 0.04)

    if timeout is not None:
        waitcall = lambda: os.waitpid(pid, os.WNOHANG)
        stop_at = time.time() + timeout
    else:
        waitcall = lambda: os.waitpid(pid, 0)

    delay = 0.0001
    while 1:
        try:
            retpid, status = waitcall()
        except OSError as err:
            if err.errno == errno.EINTR:
                delay = check_timeout(delay)
                continue
            elif err.errno == errno.ECHILD:
                # This has two meanings:
                # - pid is not a child of os.getpid() in which case
                #   we keep polling until it's gone
                # - pid never existed in the first place
                # In both cases we'll eventually return None as we
                # can't determine its exit status code.
                while 1:
                    if pid_exists(pid):
                        delay = check_timeout(delay)
                    else:
                        return None
            else:
                raise
        else:
            if retpid == 0:
                # WNOHANG was used, pid is still running
                delay = check_timeout(delay)
                continue
            # process exited due to a signal; return the integer of
            # that signal
            if os.WIFSIGNALED(status):
                return os.WTERMSIG(status)
            # process exited using exit(2) system call; return the
            # integer exit(2) system call has been called with
            elif os.WIFEXITED(status):
                return os.WEXITSTATUS(status)
            else:
                # should never happen
                raise RuntimeError("unknown process exit status")

# copy and modify from  daemon because it has bug
import os
import sys
import errno

def basic_daemonize():
    # See http://www.erlenstar.demon.co.uk/unix/faq_toc.html#TOC16
    if os.fork():   # launch child and...
        os._exit(0) # kill off parent
    os.setsid()
    if os.fork():   # launch child and...
        os._exit(0) # kill off parent again.
    os.umask(0o22)   # Don't allow others to write
    null=os.open('/dev/null', os.O_RDWR)
    for i in range(3):
        try:
            os.dup2(null, i)
        except OSError as e:
            if e.errno != errno.EBADF:
                raise
    os.close(null)


def writePID(pidfile):
    try:
        f = open(pidfile,'w')
        pid = os.getpid()
        pid = str(pid)
        f.write(pid)
    finally:
        f.close()
    if not os.path.exists(pidfile):
        raise Exception( "pidfile %s does not exist" % pidfile )


def checkPID(pidfile):
    if not pidfile:
        return
    if os.path.exists(pidfile):
        try:
            f = open(pidfile, 'r')
            pid = int(f.read())
        except ValueError:
            sys.exit('Pidfile %s contains non-numeric value' % pidfile)
        finally:
            f.close()
        try:
            os.kill(pid, 0)
        except OSError as why:
            if why[0] == errno.ESRCH:
                # The pid doesnt exists.
                print(('Removing stale pidfile %s' % pidfile))
                os.remove(pidfile)
            else:
                sys.exit("Can't check status of PID %s from pidfile %s: %s" %
                         (pid, pidfile, why[1]))
        else:
            sys.exit("Another server is running, PID %s\n" %  pid)

def daemonize(pidfile):
    checkPID(pidfile)
    basic_daemonize()
    writePID(pidfile)