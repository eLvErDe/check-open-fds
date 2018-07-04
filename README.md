# Usage

```
Usage: check_open_fds.py [-h] [-W WARNING] [-C CRITICAL] -P "systemctl show nginx --property=MainPID --value" [-D]
```

Check number of open file handlers for a given PID (through a given command returning PID)

Optional arguments:
* -h, --help  
  show this help message and exit
* -W WARNING, --warning WARNING  
  Percentage of FDs use raising a warning
* -C CRITICAL, --critical CRITICAL  
  Percentage of FDs use raising an error
* -P "systemctl show nginx --property=MainPID --value", --pid-cmd "systemctl show nginx --property=MainPID --value"  
  Command to run to select target PID
* -D, --debug  
  Debug mode: re raise Exception (do not use in production)


```
Usage: check_threads_count.py [-h] -W WARNING -C CRITICAL -P "systemctl show nginx --property=MainPID --value" [-D]
```

Check number of threads for given PID (through a given command returning PID)

optional arguments:
* -h, --help  
  show this help message and exit
* -W WARNING, --warning WARNING  
  Maximum number of threads threshold for warning
* -C CRITICAL, --critical CRITICAL  
  Maximum number of threads threshold for error
* -P "systemctl show nginx --property=MainPID --value", --pid-cmd "systemctl show nginx --property=MainPID --value"  
  Command to run to select target PID
* -D, --debug  
  Debug mode: re raise Exception (do not use in production)


# Examples

```
./check_open_fds.py --pid-cmd "systemctl show chronos --property=MainPID --value"
CRITICAL: Open FDs 100% (8188/8192) for PID 15136 is above critical 85% limit|used_percent=100%;75;85;; open_fds=8188;;;0;8192;
```

```
./check_open_fds.py --pid-cmd "echo 1234"
UNKNOWN: Got exception while running get_pid_fds: NoSuchProcess: psutil.NoSuchProcess no process found with pid 1234
```

```
./check_threads_count.py --pid-cmd 'systemctl show hbase-rest --property=MainPID --value' --warning 85 --critical 95
OK: 40 threads for PID 1117 is below warning 85 limit|threads=40;85;95;;
```
