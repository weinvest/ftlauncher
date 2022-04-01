import os
import json
import logging
from toposort import toposort_flatten
from collections import OrderedDict
from launcher import *
class Loader(object):
    def __init__(self, dconn):
        self.launchers = OrderedDict()
        self.home_root = '/home'
        self.dconn = dconn

    
    def get_launcher(self, launcher_name, user = None):
        if launcher_name not in self.launchers:
            return None
        
        launchers = self.launchers[launcher_name]
        if user is not None:
            if user in launchers:
                return launchers[user]
            else:
                return None
        elif 1 == len(launchers):
            return list(launchers.values())[0]
        else:
            logging.error('ambiguous launchers found with name %s for users: %s'
                , launcher_name
                , ''.join([u for u in launchers.keys()]))
            return None
            
    def add_launcher(self, user, launcher):
        if launcher.name not in self.launchers:
            self.launchers[launcher.name] = {user: launcher}
        else:
            self.launchers[launcher.name][user] = launcher
        
    def load_one(self, user, launcher_name, conf, home):      
        workdir = conf['work_dir']
        workdir = workdir.replace('~',  home) 
        if not os.path.exists(workdir):
            logging.warn("cann't find workdir for %s/%s:%s, ignore it's configure"
                , user
                , launcher_name
                , workdir)
            return None
        
        start_cmd = conf.get('start_cmd', '')
        if 0 == len(start_cmd) and 'all' != launcher_name:
            logging.warn("no start_cmd found for %s/%s, ignore it's configure"
                , user
                , launcher_name)
            return None
            
        out_dir = conf.get('out_dir', None)
        launcher = Launcher(user,
            launcher_name,
            home,
            workdir,
            out_dir,
            self.dconn)
        launcher.is_help = conf.get('is_help', False)
        launcher.set_start_command(start_cmd
            , conf.get('pre_start_cmd', None)
            , conf.get('post_start_cmd', None)
            , conf.get('ignore_pre_start_error', False)
            , conf.get('ignore_post_start_error', False)
            )

        get_pid_cmd = f"ps -eo pid,command | grep {launcher.cmd_user} | grep \"\-n\" | grep -v 'pid,command'| awk '{{print $1}}'|xargs -n 1 -I pp"
        default_stop_cmd = f"{get_pid_cmd} kill pp"
        launcher.set_stop_command(conf.get('stop_cmd', default_stop_cmd)
            , conf.get('pre_stop_cmd', None)
            , conf.get('post_stop_cmd', None)
            , conf.get('ignore_pre_stop_error', False)
            , conf.get('ignore_post_stop_error', False)
            )

        default_status_cmd = f"{get_pid_cmd} ps -o pid,stat,time,command --no-headers  --pid pp"
        launcher.set_status_command(conf.get('status_cmd', default_status_cmd))
        
        dependence_names = conf.get('dependences', [])
        launcher.dependence_names = dependence_names if isinstance(dependence_names, list) else dependence_names.split()
        self.add_launcher(user, launcher)
        logging.info('load launcher %s success', launcher_name)
        return launcher
        
    def load_4_user(self, user, home):
        conf_dir_4_user = '.ftapp.conf'
        if not os.path.exists(conf_dir_4_user):
            return

        logging.info('load_4_user {0}'.format(user))
        try:
            user_all_launchers = []
            oldcwd = os.getcwd()
            os.chdir(conf_dir_4_user)
            
            conf_files = os.listdir('.')
            logging.info(f'{user} have configured:{conf_files}')

            for conf_file_name in conf_files:
                launcher_name, conf_ext = os.path.splitext(conf_file_name)
                if u'.json' != conf_ext:
                   continue
                
                try:
                    logging.info('loading launcher {0}'.format(launcher_name))
                    full_name = f'{user}/{launcher_name}'
                    launcher = self.get_launcher(launcher_name, user)
                    
                    if launcher is not None:
                        continue

                    conf_file = open(conf_file_name, 'r')
                    conf = json.load(conf_file)

                    launcher = self.load_one(user, launcher_name, conf, home)
                    if not launcher.is_help:
                        user_all_launchers.append(full_name)

                except Exception as e:
                    logging.error("load launcher %s/%s failed, detail:%s", user, launcher_name, str(e))
        finally:
            if 0 != len(user_all_launchers):
                user_all_conf = {"work_dir":"~", "dependences":user_all_launchers}
                try:
                    self.load_one(user, 'all', user_all_conf, home)
                except Exception as e:
                    logging.error(f"load launcher {user}/all failed, detail:{str(e)}")

            os.chdir(oldcwd)
        
    def load(self, home_root):
        users = os.listdir(home_root)
        for user in users:
            home = os.path.join(home_root, user)
            self.load_user(user, home)

    def load_user(self, user, home):
        oldcwd = os.getcwd()
        try:
            os.chdir(home)
            self.load_4_user(user, home)
        finally:
            os.chdir(oldcwd)       

    def split_launcher_name(self, full_name):
        user = None
        dep_name = full_name
        if '/' in str(full_name):
            user, dep_name = full_name.split('/')
            
        return (user, dep_name)
        
    def resolve(self):
        from collections import defaultdict
        used_for_toposort = defaultdict(list)
        for launcher_name, launchers in self.launchers.items():
            for user, launcher in launchers.items():
                is_resoloved = True
                for dependence_name in launcher.dependence_names:
                    dep_user, dep_name = self.split_launcher_name(dependence_name)
                    dep_launcher = self.get_launcher(dep_name, dep_user)
                    
                    if dep_launcher is not None:
                        logging.info(f"resolove {user}/{launcher.name}'s depency {dependence_name}")
                        launcher.add_dependence(dep_launcher)
                        used_for_toposort[launcher].append(dep_launcher)
                    else:
                        is_resoloved = False
                launcher.is_resoloved = is_resoloved

        try:
            self.launchers = OrderedDict()
            sorted_launchers = toposort_flatten(used_for_toposort, False)
            for idx , launcher in enumerate(sorted_launchers):
                launcher.dep_idx = idx
                self.add_launcher(launcher.user, launcher)

            logging.error(f'toposort launchers success')
        except Exception as e:
            logging.error(f'toposort launchers failed: {e}')
            return

        try:
            for launcher in sorted_launchers:
                launcher.sort_dependences()
            logging.info('sort launchers deps success')

        except Exception as e:
            logging.error(f'sort launchers deps failed: {e}')


    def list(self, user=None):
        result = []
        for launcher_name, launchers in self.launchers.items():
            for user1, launcher in launchers.items():
                if user is None or user == user1:
                    result.append('{0}/{1}'.format(user1, launcher_name))
        
        result = sorted(result)
        return result
