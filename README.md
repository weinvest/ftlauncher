# ftlauncher

### 简介:

ftlauncher是一个类似与sysctl的工具，可以使用start/stop/status来启动配置好的程序，不同之处在于:

1. 配置文件分布在不同的用户下 
2. 不以root启动程序，以配置文件所在的用户启动程序 

正是这2点不同，使得ftlauncher可以用来赋予没有登陆权限的人一些预定义的运维权限

### 使用:

如下, 我们有一台名为TKY的机器:

```
├── /home
│   ├── OPERATOR
│   ├── TKY_A
│   │   └── .ftapp.conf
│   │       ├── app_a1.json
│   │       └── app_a2.json
│   └── TKY_B
│       └── .ftapp.conf
│           ├── app_b1.json
│           └── app_b2.json  #dep TKY_B/app_b1
└── /root
    └── .ftapp.conf
        └── moni.json
```

运维人员使用用户OPERATOR登陆，然后就可以运维一些部署在其他用户下的程序
**ftlauncher ls**

```
/root/moni
/TKY_A/app_a1
/TKY_A/app_a2
/TKY_B/app_b1
/TKY_B/app_b2
```

ls也只输出指定用户下的配置
**ftlauncher ls TKY_A**

```
/TKY_A/app_a1
/TKY_A/app_a2
```

**ftlauncher start TKY_A/app_a1**
输出app_a1中定义的命令或者出错信息

**ftlauncher start TKY_B/app_b2 true**
因为app_b2依赖与TKY_B/app_b1, 同时参数中的true表示需要执行依赖项，
所以首先会执行输出TKY_B1/app_b1的结果，然后执行输出TKY_B/app_b2的结果

**ftlauncher status TKY_B/app_b2**
输出TKY_B/app_b2的状态信息

**ftlauncher status TKY_B/app_b2 true**

首先TKY_B/app_b1的状态信息，然后输出TKY_B/app_b2的状态信息

**ftlauncher stop TKY_B/app_b2**

stop掉TKY_B/app_b2

**ftlauncher stop  TKY_B/app_b2 true**

stop掉TKY_B/app_b1，然后stop TKY_B/app_b2

### 配置(TKY_B/app_b2)

```json
{
    "work_dir": "~/apps",
    "out_dir": "~",

    "start_cmd": "taskset -c 1 ./ob -n $(whoami)_R -t $(($(date +%s)-10)) -f $(whoami).X '.*' 000000 1m -z 1 -s 50 -w 5 -d ~/data",
    "#pre_start_cmd": "",
    "#post_start_cmd": "",
    "ignore_pre_start_error": false,
    "ignore_post_start_error": false,
    
    "#stop_cmd": "ps aux|grep -h $(whoami) | grep -Evh 'grep|ftlauncher|su|sshd' | awk '{{print $2}}'|xargs -n 1 -I p kill p",
    "#pre_stop_cmd": "",
    "#post_stop_cmd": "",
    "ignore_pre_stop_error": false,
    "ignore_post_stop_error": false,
    
    "#status_cmd": "ps aux|grep -h $(whoami) | grep -Evh 'grep|ftlauncher|su|sshd'",
    
    "dependences": "TKY_B/app_b1"

}
```


