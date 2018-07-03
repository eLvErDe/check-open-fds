# Usage

```
Usage: check_open_fds.py [-h] [-W WARNING] [-C CRITICAL] -P "systemctl show nginx --property=MainPID --value"
```

Check number of open file handlers for a given PID (through a given command
returning PID)

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
