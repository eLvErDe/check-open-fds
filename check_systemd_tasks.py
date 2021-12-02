#!/usr/bin/python3
#
# https://github.com/eLvErDe/check-open-fds
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
Check systemd tasks count
"""

import re
import sys
import subprocess
import argparse
import functools

DEBUG = False


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

    argparser = NagiosArgumentParser(description='Check number of running tasks for a systemd service')
    argparser.add_argument('-W', '--warning',  type=int, default=75, help='Percentage of tasks running/task limits used raising a warning')  # pylint: disable=bad-whitespace
    argparser.add_argument('-C', '--critical', type=int, default=85, help='Percentage of tasks running/task limits used raising an error')  # pylint: disable=bad-whitespace
    argparser.add_argument('-S', '--service',  required=True,        help='Systemd service name to be checked', metavar="apache2.service")  # pylint: disable=bad-whitespace
    argparser.add_argument('-D', '--debug',    action='store_true',  help='Debug mode: re raise Exception (do not use in production)')  # pylint: disable=bad-whitespace
    args = argparser.parse_args()

    if args.warning > args.critical:
        argparser.error('Warning threshold cannot be greater than critical one')

    if args.warning < 0 or args.warning > 100 or args.critical < 0 or args.critical > 100:
        argparser.error('Warning/critical tresholds must be a percentage between and 100')

    return args

@tb2unknown
def check_task_accounting_enabled_or_raise(service: str) -> None:
    """
    Execute systemctl show <service> --property TasksAccounting and raise if not enabled

    :param service: Systemd service to query, e.g: apache2.service
    :type service: str
    :raise RuntimeError: If task accounting is not enabled
    """

    # Cannot use --value here to support CentOS 7
    command = ["systemctl", "show", service, "--property", "TasksAccounting"]
    command_str = " ".join(command)

    sub_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    stdout, stderr = sub_process.communicate()

    assert sub_process.returncode == 0, 'Command %s return exit code != 0: output: %s %s' % (command_str, stdout, stderr)
    if not stdout.strip() == b"TasksAccounting=yes":
        raise RuntimeError("Command %s returned stdout %s says task accounting is not enable" % (command_str, stdout))


@tb2unknown
def get_int_value_from_systemctl(service: str, prop: str) -> int:
    """
    Execute systemctl show <service> --property <prop> --value and return value as integer

    :param service: Systemd service to query, e.g: apache2.service
    :type service: str
    :param prop: Propert to be requested, e.g: TasksCurrent
    :type prop: str
    :return: Integer value returned by systemd
    :rtype: int
    """

    # Cannot use --value here to support CentOS 7
    command = ["systemctl", "show", service, "--property", prop]
    command_str = " ".join(command)

    sub_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    stdout, stderr = sub_process.communicate()

    assert sub_process.returncode == 0, 'Command %s return exit code != 0: output: %s %s' % (command_str, stdout, stderr)
    assert re.match(rb"^%s=[0-9]+$" % bytes(prop, "utf-8"), stdout.strip()), 'Command %s returned stdout %s cannot be converted to integer' % (command_str, stdout)

    return int(stdout.strip().split(b"=")[1])


if __name__ == '__main__':

    CONFIG = parse_args()
    DEBUG = CONFIG.debug

    check_task_accounting_enabled_or_raise(CONFIG.service)
    USED, MAX = get_int_value_from_systemctl(CONFIG.service, "TasksCurrent"), get_int_value_from_systemctl(CONFIG.service, "TasksMax")

    PERCENTAGE = int(round(USED * 100.0 / MAX))

    PERFDATA = [
        'tasks_percent=%d%%;%d;%d;;' % (PERCENTAGE, CONFIG.warning, CONFIG.critical),
        'tasks=%d;;;%d;%d;' % (USED, 0, MAX),
    ]


    if PERCENTAGE > CONFIG.critical:
        MESSAGE = 'CRITICAL: Tasks %d%% (%d/%d) for service %s is above critical %d%% limit' % (PERCENTAGE, USED, MAX, CONFIG.service, CONFIG.critical)
        CODE = 2
    elif PERCENTAGE > CONFIG.warning:
        MESSAGE = 'WARNING: Tasks %d%% (%d/%d) for service %s is above warning %d%% limit' % (PERCENTAGE, USED, MAX, CONFIG.service, CONFIG.warning)
        CODE = 1
    else:
        MESSAGE = 'OK: Tasks %d%% (%d/%d) for service %s is below warning %d%% limit' % (PERCENTAGE, USED, MAX, CONFIG.service, CONFIG.warning)
        CODE = 0

    print('%s|%s' % (MESSAGE, ' '.join(PERFDATA)))
    sys.exit(CODE)
