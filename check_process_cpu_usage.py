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
Nagios-style monitoring script to check and graph a single process CPU usage
"""


import os
import re
import sys
import json
import tempfile
import argparse
import functools
import subprocess
from typing import NamedTuple, Callable, TypeVar, Any, Optional

try:
    import psutil  # type: ignore
except ImportError:
    print("UNKNOWN: Please apt-get install python3-psutil or yum install python36-psutil")
    sys.exit(3)

# Custom type to preverse original return type when using a decorator
ReturnType = TypeVar("ReturnType")

DEBUG = False


def tb2unknown(method: Callable[..., ReturnType]) -> Callable[..., ReturnType]:
    """
    Decorator to exit with Nagios code 3 (Unknown) in case of exception

    :param method: Original method decorator with this function
    :type method: callable
    :return: Original decorator method return of informative message and exist with code 3 in case of exception
    :rtype: original
    """

    @functools.wraps(method)
    def wrapped(*args: Any, **kwargs: Any) -> ReturnType:
        """Run real method"""
        try:
            f_result = method(*args, **kwargs)
            return f_result
        except Exception as exc:  # pylint: disable=broad-except
            print("UNKNOWN: Got exception while running %s: %s: %s" % (method.__name__, exc.__class__.__name__, exc))
            if DEBUG:
                raise
            sys.exit(3)

    return wrapped


class NagiosThreshold:  # pylint: disable=too-few-public-methods
    """
    Evaluate Nagios threshold, see https://nagios-plugins.org/doc/guidelines.html#THRESHOLDFORMAT
    for documentation regarding format

    :param raw: Nagios threshold as text, e.g: 10, 10:, ~:10, 10:20 or @10:20
    :type raw: str
    """

    def __init__(self, raw: str) -> None:
        assert isinstance(raw, str) and raw, "raw parameter must be a non-empty string"
        matcher = re.match(r"^(?P<is_inclusive>@?)((?P<low_boundary>(\d+(\.\d+)?|~))?:)?(?P<high_boundary>\d+(\.\d+)?)?", raw)
        assert matcher is not None, "cannot parsed threshold %s, did not match regexp" % raw
        matched = matcher.groupdict()

        self.inclusive = bool(matched["is_inclusive"])
        low_boundary = matched["low_boundary"]
        if matched["low_boundary"] is None:
            self.low_boundary: float = 0
        elif matched["low_boundary"] == "~":
            self.low_boundary = float("-inf")
        else:
            self.low_boundary = float(low_boundary)
        self.high_boundary = float(matched["high_boundary"]) if matched["high_boundary"] is not None else float("inf")

        #print("Threshold %s converted to low_boundary=%s, high_boundary=%s, inclusive=%s" % (raw, self.low_boundary, self.high_boundary, self.inclusive))

    def is_outside_boundaries(self, number: float) -> Optional[str]:
        """
        Check if given number is outside boundaries and return string representing test that failed

        :param number: Any float or integer to test against boundaries
        :type number: float
        :return: Message representing the test that failed or None of provided number is inside boundaries
        :rtype: str, optional
        """

        assert isinstance(number, (float, int)), "number parameter must be a float or int"

        if self.inclusive:
            if number < self.low_boundary:
                return "%s<%s" % (number, self.low_boundary)
            if number > self.high_boundary:
                return "%s>%s" % (number, self.high_boundary)
        else:
            if number <= self.low_boundary:
                return "%s<=%s" % (number, self.low_boundary)
            if number >= self.high_boundary:
                return "%s>=%s" % (number, self.high_boundary)

        return None


class NagiosArgumentParser(argparse.ArgumentParser):
    """
    Inherit from ArgumentParser but exit with Nagios code 3 (Unknown) in case of argument error
    """

    def error(self, message):
        print("UNKNOWN: Bad arguments (see --help): %s" % message)
        sys.exit(3)


class CpuTimesNamedTuple(NamedTuple):
    """
    Typed named tuple representing psutil cpu_times result, inspired by psutil code itself, documentation is actually completely stolen
    from psutil doc

    :param pid: Process PID, make no sens to track CPU usage among different run if the PID has changed
    :type pid: int
    :param timestamp: Unix time of the measure (so it can be diffed), according to psutil it's using time.monotonic() * number of CPUs (why ?)
    :type timestamp: float
    :param user: Time spent in user mode
    :type user: float
    :param system: Time spent in kernel mode
    :type system: float
    :param children_user: User time of all child processes
    :type children_user: float
    :param children_system: System time of all child processes
    :type children_system: float
    :param iowait: Time spent waiting for blocking I/O to complete, this value is excluded from user and system times count
        (because the CPU is not doing any work)
    :type iowait: float
    """

    pid: int
    timestamp: float
    user: float
    system: float
    children_user: float
    children_system: float
    iowait: float

    @tb2unknown
    def save_to_disk(self, path: str) -> None:
        """
        Save this named tuple instance to disk at given path

        :param path: String representing path to save the namedtuple to
        :type path: str
        """

        with open(path, "w", encoding="utf-8") as path_fh:
            json.dump(self._asdict(), path_fh)  # pylint: disable=no-member

    # No @tb2unknown because this is expected to fail on first run
    @classmethod
    def load_from_disk(cls, path: str) -> "CpuTimesNamedTuple":
        """
        Load a file representing an instance of this class

        :param path: String representing path to load the namedtuple from
        :type path: str
        :return: Instance of CpuTimesNamedTuple namedtuple
        :rtype: CpuTimesNamedTuple
        """

        with open(path, "r", encoding="utf-8") as path_fh:
            data = json.load(path_fh)
            return cls(**data)


def parse_args() -> argparse.Namespace:
    """
    Parse command line arguments and return object representing all properties

    :return: Namespace object representing all command line arguments and their values
    :rtype: argparse.Namespace
    """

    argparser = NagiosArgumentParser(description=__doc__.strip())
    argparser.add_argument(
        "-W", "--warning", type=str, required=True, help="Warning threshold using Nagios-style value (e.g: 10 for >0%% and <10%%, @10:20 for >=10%% and <=20%%"
    )
    argparser.add_argument(
        "-C",
        "--critical",
        type=str,
        required=True,
        help="Critical threshold using Nagios-style value (e.g: 10 for >0%% and <10%%, @10:20 for >=10%% and <=20%%",
    )
    argparser.add_argument(
        "-P", "--pid-cmd", required=True, help="Command to run to select target PID", metavar='"systemctl show nginx --property=MainPID --value"'
    )
    argparser.add_argument("-D", "--debug", action="store_true", help="Debug mode: re raise Exception (do not use in production)")
    args = argparser.parse_args()

    return args


@tb2unknown
def get_pid_from_command(shell_command: str) -> int:
    """
    Execute given command a return psutil process object

    :param shell_command: String representing command to be run to get process PID
    :type shell_command: str
    :raise AssertionError: If command failed or command stdout does not look like a PID
    :return: Process PID to check CPU usage for
    :rtype: int
    """

    sub_process = subprocess.Popen(shell_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    stdout, stderr = sub_process.communicate()

    assert sub_process.returncode == 0, "Command return exit code != 0: output: %s %s" % (str(stdout, "utf-8"), str(stderr, "utf-8"))
    assert stdout.strip().isdigit(), "Command return stdout %s that cannot be converter to PID (integer)" % str(stdout, "utf-8")

    return int(stdout)


@tb2unknown
def get_pid_cpu_percent(pid: int, buffer_file: str) -> float:
    """
    Return process CPU usage and takes care of loading and saving current state to a JSON file so it can be diffed for next run

    :param pid: Process pid to check
    :type pid: int
    :param buffer_file: Path to file storing counter to be able to diff with previous run
    :type buffer_file: str
    :return: Process CPU usage in percent as float (between 0 and 100 * nb cpus)
    :rtype: float
    """

    process = psutil.Process(pid)
    assert process.is_running(), "PID %d is not running" % pid

    has_load_missing = False
    has_load_error = False
    has_pid_changed = False
    exc: Optional[Exception] = None
    try:
        previous = CpuTimesNamedTuple.load_from_disk(buffer_file)
    except FileNotFoundError as exc1:
        has_load_missing = True
        exc = exc1
    except Exception as exc2:  # pylint: disable=broad-except
        has_load_error = True
        exc = exc2

    if not has_load_missing and not has_load_error and previous.pid != pid:
        has_pid_changed = True

    # Reload previous state into Process instance
    if not has_load_missing and not has_load_error and not has_pid_changed:
        process._last_sys_cpu_times = previous.timestamp  # pylint: disable=protected-access
        process._last_proc_cpu_times = psutil._pslinux.pcputimes(  # pylint: disable=protected-access
            user=previous.user, system=previous.system, children_user=previous.children_user, children_system=previous.children_user, iowait=previous.iowait
        )

    cpu_percent = process.cpu_percent()

    # Parse values store in psutil Process instance and store them for next run
    parsed = CpuTimesNamedTuple(
        pid=pid,
        timestamp=process._last_sys_cpu_times,  # pylint: disable=protected-access
        user=process._last_proc_cpu_times.user,  # pylint: disable=protected-access
        system=process._last_proc_cpu_times.system,  # pylint: disable=protected-access
        children_user=process._last_proc_cpu_times.children_user,  # pylint: disable=protected-access
        children_system=process._last_proc_cpu_times.children_system,  # pylint: disable=protected-access
        iowait=process._last_proc_cpu_times.iowait,  # pylint: disable=protected-access
    )
    parsed.save_to_disk(buffer_file)

    # Cannot continue, will work next run
    if has_load_missing:
        raise RuntimeError("First run, creating buffers at %s: %s: %s" % (buffer_file, exc.__class__.__name__, exc))
    if has_load_error:
        raise RuntimeError("Buffer file at %s was corrupted: %s: %s" % (buffer_file, exc.__class__.__name__, exc))
    if has_pid_changed:
        raise RuntimeError("Process pid has changed from %d to %s" % (previous.pid, pid))

    return cpu_percent


if __name__ == "__main__":

    CONFIG = parse_args()
    DEBUG = CONFIG.debug

    PID = get_pid_from_command(CONFIG.pid_cmd)
    BUFFER_PATH = os.path.join(tempfile.gettempdir(), os.path.basename(__file__) + "_pid_%d.json" % PID)
    CPU_PERCENT = get_pid_cpu_percent(PID, BUFFER_PATH)

    THRESHOLD_WARNING = NagiosThreshold(CONFIG.warning)
    THRESHOLD_CRITICAL = NagiosThreshold(CONFIG.critical)

    OUTSIDE_THRESHOLD_WARNING = THRESHOLD_WARNING.is_outside_boundaries(CPU_PERCENT)
    OUTSIDE_THRESHOLD_CRITICAL = THRESHOLD_CRITICAL.is_outside_boundaries(CPU_PERCENT)

    PERFDATA = [
        "cpu_percentage=%.1f%%;%s..%s;%s..%s;0;%d" % (
            CPU_PERCENT,
            THRESHOLD_WARNING.low_boundary,
            THRESHOLD_WARNING.high_boundary,
            THRESHOLD_CRITICAL.low_boundary,
            THRESHOLD_CRITICAL.high_boundary,
            psutil.cpu_count() * 100,
        ),
        #"cpu_percentage=%.1f%%;;;0;%d" % (CPU_PERCENT, psutil.cpu_count() * 100),
    ]

    if OUTSIDE_THRESHOLD_CRITICAL:
        MESSAGE = "CRITICAL: %1.f%% CPU usage for PID %d is outside critical limits (%s)" % (CPU_PERCENT, PID, OUTSIDE_THRESHOLD_CRITICAL)
        CODE = 2
    elif OUTSIDE_THRESHOLD_WARNING:
        MESSAGE = "WARNING: %.1f%% CPU usage for PID %d is outside warning limits (%s)" % (CPU_PERCENT, PID, OUTSIDE_THRESHOLD_WARNING)
        CODE = 1
    else:
        MESSAGE = "OK: %.1f%% CPU usage for PID %d is inside limits (%s%s%s and %s%s%s)" % (
            CPU_PERCENT,
            PID,
            CPU_PERCENT,
            ">=" if THRESHOLD_WARNING.inclusive else ">",
            THRESHOLD_WARNING.low_boundary,
            CPU_PERCENT,
            "<=" if THRESHOLD_WARNING.inclusive else "<",
            THRESHOLD_WARNING.high_boundary,
        )
        CODE = 0

    print("%s|%s" % (MESSAGE, " ".join(PERFDATA)))
    sys.exit(CODE)
