import os
import json
import logging
from launcher import *
class Loader(object):
    def __init__(self, dconn):
        self.launchers = {}
        self.last_update_times = {}
        self.home_root = '/home'
        self.logger = logging.getLogger()

        self.logf = logging.FileHandler('ftlauncher.log', mode='w')
        self.logf.setLevel(logging.DEBUG)
        self.logger.addHandler(self.logf)
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
            self.logger.error('ambiguous launchers found with name %s for users: %s'
                , launcher_name
                , ''.join([u for u in launchers.keys()]))
            return None
            
    def add_launcher(self, user, launcher):
        if launcher.name not in self.launchers:
            self.launchers[launcher.name] = {user: launcher}
        else:
            self.launchers[launcher.name][user] = launcher
        
    def load_one(self, user, launcher_name, conf_file_name, home_root):
        try:
            conf_file = open(conf_file_name, 'r')
            conf = json.load(conf_file)
        except Exception as e:
            self.logger.warn('open conf file %s failed: %s', conf_file_name, str(e))
            return
            
        workdir = conf['work_dir']
        workdir = workdir.replace('~',  f'{home_root}/{user}') 
        if not os.path.exists(workdir):
            self.logger.warn("cann't find workdir for %s/%s:%s, ignore it's configure"
                , user
                , launcher_name
                , workdir)
            return
        
        start_cmd = conf.get('start_cmd', None)
        if 0 == len(start_cmd):
            self.logger.warn("not start_cmd found for %s/%s, ignore it's configure"
                , user
                , launcher_name)
            return
            
        out_dir = conf.get('out_dir', None)
        launcher = Launcher(user,
            launcher_name,
            os.path.join(home_root, user),
            workdir,
            out_dir,
            self.dconn)
        launcher.set_start_command(start_cmd
            , conf.get('pre_start_cmd', None)
            , conf.get('post_start_cmd', None)
            , conf.get('ignore_pre_start_error', False)
            , conf.get('ignore_post_start_error', False)
            )

        default_stop_cmd = f"ps aux|grep -h {launcher.cmd_user} | grep -Evh 'grep|ftlauncher|su|sshd' | awk '{{print $2}}'|xargs -n 1 -I p kill p"
        launcher.set_stop_command(conf.get('stop_cmd', default_stop_cmd)
            , conf.get('pre_stop_cmd', None)
            , conf.get('post_stop_cmd', None)
            , conf.get('ignore_pre_stop_error', False)
            , conf.get('ignore_post_stop_error', False)
            )

        default_status_cmd = f"ps aux|grep -h {launcher.cmd_user} | grep -Evh 'grep|ftlauncher|su|sshd'"
        launcher.set_status_command(conf.get('status_cmd', default_status_cmd))
        
        dependence_names = conf.get('dependences', '')
        launcher.dependence_names = dependence_names.split()
        self.add_launcher(user, launcher)
        self.logger.info('load launcher %s success', launcher_name)
        
    def load_4_user(self, user, home_root):
        conf_dir_4_user = '.ftapp.conf'
        if not os.path.exists(conf_dir_4_user):
            return

        self.logger.info('load_4_user {0}'.format(user))
        try:
            oldcwd = os.getcwd()
            os.chdir(conf_dir_4_user)
            
            conf_files = os.listdir('.')
            self.logger.info(f'{user} have configured:{conf_files}')
            for conf in conf_files:
                last_update_time = os.path.getmtime(conf)
                launcher_name, conf_ext = os.path.splitext(conf)
                if u'.json' != conf_ext:
                   continue
                
                try:
                    self.logger.info('loading launcher {0}'.format(launcher_name))
                    full_name = '{0}/{1}'.format(user, launcher_name)
                    launcher = self.get_launcher(launcher_name, user)
                    lan_last_update_time = self.last_update_times.get(full_name, 0)
                    if launcher is None:
                        self.load_one(user, launcher_name, conf, home_root)
                    elif last_update_time > lan_last_update_time:
                        self.last_update_times[full_name] = last_update_time
                        self.load_one(user, launcher_name, conf, home_root)
                except Exception as e:
                    self.logger.error("load launcher %s/%s failed, detail:%s", user, launcher_name, str(e))
        finally:
            os.chdir(oldcwd)
        
    def load(self, home_root):
        users = os.listdir(home_root)
        for user in users:
            home = os.path.join(home_root, user)
            self.load_user(user, home, home_root)

    def load_user(self, user, home, home_root):
        oldcwd = os.getcwd()
        try:
            os.chdir(home)
            self.load_4_user(user, home_root)
        finally:
            os.chdir(oldcwd)       

    def split_launcher_name(self, full_name):
        user = None
        dep_name = full_name
        if '/' in str(full_name):
            user, dep_name = full_name.split('/')
            
        return (user, dep_name)
        
    def resolve(self):
        for launcher_name, launchers in self.launchers.items():
            for user, launcher in launchers.items():
                is_resoloved = True
                for dependence_name in launcher.dependence_names:
                    dep_user, dep_name = self.split_launcher_name(dependence_name)
                    dep_launcher = self.get_launcher(dep_name, dep_user)
                    
                    if dep_launcher is not None:
                        logging.info(f"resolove {user}/{launcher.name}'s depency {dep_user}/{dependence_name}")
                        launcher.add_dependence(dep_launcher)
                    else:
                        is_resoloved = False
                launcher.is_resoloved = is_resoloved
                
    def list(self, user=None):
        result = []
        for launcher_name, launchers in self.launchers.items():
            for user1, launcher in launchers.items():
                if user is None or user == user1:
                    result.append('{0}/{1}'.format(user1, launcher_name))
        
        return result
        
