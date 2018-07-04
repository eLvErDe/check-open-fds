#!/usr/bin/python3
#
# This is free and unencumbered software released into the public domain.
#
# Anyone is free to copy, modify, publish, use, compile, sell, or
# distribute this software, either in source code form or as a compiled
# binary, for any purpose, commercial or non-commercial, and by any
# means.
#
# In jurisdictions that recognize copyright laws, the author or authors
# of this software dedicate any and all copyright interest in the
# software to the public domain. We make this dedication for the benefit
# of the public at large and to the detriment of our heirs and
# successors. We intend this dedication to be an overt act of
# relinquishment in perpetuity of all present and future rights to this
# software under copyright law.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
#
# For more information, please refer to <http://unlicense.org>

# pylint: disable=line-too-long

"""
Check threads count
"""

import sys
import subprocess
import argparse
import functools

DEBUG = False


try:
    import psutil
except ImportError:
    print('UNKNOWN: Please apt-get install python3-psutil or yum install python34-psutil')
    sys.exit(3)


# ArgumentParser with single-line stdout output and unknown state Nagios return code
class NagiosArgumentParser(argparse.ArgumentParser):
    """
    Inherit from ArgumentParser but exit with Nagios code 3 (Unknown)
    in case of argument error
    """

    def error(self, message):
        print('UNKNOWN: Bad arguments (see --help): %s' % message)
        sys.exit(3)


# Nagios unknown exit decorator in case of TB
def tb2unknown(method):
    """
    Decorator to exit with Nagios code 3 (Unknown)
    in case of exception
    """

    @functools.wraps(method)
    def wrapped(*args, **kw):
        """ Run real method """
        try:
            f_result = method(*args, **kw)
            return f_result
        except Exception as exc:  # pylint: disable=broad-except
            print('UNKNOWN: Got exception while running %s: %s: %s' % (method.__name__, exc.__class__.__name__, exc))
            if DEBUG:
                raise
            sys.exit(3)
    return wrapped


def parse_args():
    """
    Parse command line arguments
    """

    argparser = NagiosArgumentParser(description='Check number of threads for given PID (through a given command returning PID)')
    argparser.add_argument('-W', '--warning',  type=int, required=True, help='Maximum number of threads threshold for warning')  # pylint: disable=bad-whitespace
    argparser.add_argument('-C', '--critical', type=int, required=True, help='Maximum number of threads threshold for error')  # pylint: disable=bad-whitespace
    argparser.add_argument('-P', '--pid-cmd',  required=True,        help='Command to run to select target PID', metavar='"systemctl show nginx --property=MainPID --value"')  # pylint: disable=bad-whitespace
    argparser.add_argument('-D', '--debug',    action='store_true',  help='Debug mode: re raise Exception (do not use in production)')  # pylint: disable=bad-whitespace
    args = argparser.parse_args()

    if args.warning > args.critical:
        argparser.error('Warning threshold cannot be greater than critical one')

    if args.warning < 0 or args.critical < 0:
        argparser.error('Warning/critical tresholds must be > 0')

    return args


@tb2unknown
def get_pid_from_command(shell_command):
    """
    Execute given command a return psutil
    process object
    """

    sub_process = subprocess.Popen(shell_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    stdout, stderr = sub_process.communicate()

    assert sub_process.returncode == 0, 'Command return exit code != 0: output: %s %s' % (stdout, stderr)
    assert stdout.strip().isdigit(), 'Command return stdout %s that cannot be converter to PID (integer)' % stdout

    return int(stdout)


@tb2unknown
def get_pid_threads_count(pid):
    """
    Return number of threads for a running PID
    """

    process = psutil.Process(pid)
    assert process.is_running(), 'PID %d is not running' % pid

    threads_count = process.num_threads()

    return threads_count


if __name__ == '__main__':

    CONFIG = parse_args()
    DEBUG = CONFIG.debug

    PID = get_pid_from_command(CONFIG.pid_cmd)
    THREADS_COUNT = get_pid_threads_count(PID)

    PERFDATA = [
        'threads=%d;%d;%d;;' % (THREADS_COUNT, CONFIG.warning, CONFIG.critical),
    ]


    if THREADS_COUNT > CONFIG.critical:
        MESSAGE = 'CRITICAL: %d threads for PID %d is above critical %d limit' % (THREADS_COUNT, PID, CONFIG.critical)
        CODE = 2
    elif THREADS_COUNT > CONFIG.warning:
        MESSAGE = 'WARNING: %d threads for PID %d is above warning %d limit' % (THREADS_COUNT, PID, CONFIG.warning)
        CODE = 1
    else:
        MESSAGE = 'OK: %d threads for PID %d is below warning %d limit' % (THREADS_COUNT, PID, CONFIG.warning)
        CODE = 0

    print('%s|%s' % (MESSAGE, ' '.join(PERFDATA)))
    sys.exit(CODE)
