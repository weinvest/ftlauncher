import os
import json
import logging
from launcher import *
class Loader(object):
    def __init__(self):
        self.launchers = {}
        self.last_update_times = {}
    
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
        
    def load_one(self, user, launcher_name):
        try:
            conf_file = open(launcher_name, 'r')
            conf = json.load(conf_file)
        except:
            return
            
        workdir = conf['workdir']
        if os.path.exists(workdir):
            logging.warn("cann't find workdir for %s/%s:%s, ignore it's configure"
                , user
                , launcher_name
                , workdir)
            return
        
        start_cmd = conf.get('start_cmd', None)
        if 0 == len(start_cmd):
            logging.warn("not start_cmd found for %s/%s, ignore it's configure"
                , user
                , launcher_name)
            return
            
        exe_name = start_cmd.split()[0]
        default_stop_cmd = "kill -15 `ps aux|grep -h {0} | grep -h {1} | awk '{print $2}'`".format(exe_name, launcher_name)
        default_status_cmd = 'ps aux|grep -h {0}|grep -h {1}'.format(exe_name, launcher_name)
        launcher = launcher.Launcher(user, launcher_name, workdir)
        launcher.set_start_command(start_cmd
            , conf.get('pre_start_cmd', None)
            , conf.get('post_start_cmd', None))
        launcher.set_stop_command(conf.get('stop_cmd', default_stop_cmd)
            , conf.get('pre_stop_cmd', None)
            , conf.get('post_stop_cmd', None))
        launcher.set_status_command(conf.get('status_cmd', default_status_cmd))
        
        dependence_names = conf.get('dependences', [])
        launcher.dependence_names = dependence_names
        self.add_launcher(launcher)
        
    def load_4_user(self, user):
        conf_dir_4_user = os.path.join(user, '.ftapp.conf')
        if not os.path.exists(conf_dir_4_user):
            return
        
        try:
            oldcwd = os.getcwd()
            os.chdir(conf_dir_4_user)
            
            conf_files = os.listdir('.')
            for conf in conf_files:
                last_update_time = os.path.getmtime(conf)
                launcher_name, conf_ext = os.path.splitext(conf)
                if '.json' != conf_ext:
                   continue
                
                try:
                    full_name = '{0}/{1}'.format(user, launcher_name)
                    launcher = self.get_launcher(launcher_name, user)
                    lan_last_update_time = self.last_update_times.get(full_name, 0)
                    if launcher is None:
                        self.load_one(user, conf)
                    elif last_update_time < lan_last_update_time:
                        self.last_update_times[full_name] = lan_last_update_time
                        self.load_one(user, conf)
                except Exception as e:
                    logging.error("load launcher %s/%s failed, detail:%s", user, conf_stem, str(e))
        finally:
            os.chdir(oldcwd)
        
    def load(self):
        home_root = '/home'
        users = os.listdir(home_root)
        for user in users:
            oldcwd = os.getcwd()
            try:
                self.load_4_user(user)
            finally:
                os.chdir(oldcwd)
    def split_launcher_name(self, full_name):
        user = None
        dep_name = full_name
        if '/' in dependence_name:
            user, dep_name = dependence_name.split('/')
            
        return (user, dep_name)
        
    def resolve(self):
        for launcher_name, launchers in self.launchers.items():
            for user, launcher in launchers.items():
                is_resoloved = True
                for dependence_name in launcher.dependence_names:
                    user, dep_name = self.split_launcher_name(dependence_name)
                    dep_launcher = self.get_launcher(dep_name, user)
                    
                    if dep_launcher is not None:
                        launcher.add_dependence(dep_launcher)
                    else:
                        is_resoloved = False
                launcher.is_resoloved = is_resoloved
                
    def list(self, user=None):
        result = []
        
        for launcher_name, launchers in self.launchers.items():
            for user1, launcher in launchers.items():
                if user is None or user == user1:
                    result.append('{0}/{1}'.format(user, launcher_name))
        
        return result
        
