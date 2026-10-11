"""
Function definition
  Wrapper for the python subprocess module
"""

import logging
import subprocess
from typing import Optional, List, Union


def arm_subprocess(cmd: Union[str, List[str]], shell=False, check=False, timeout=None) -> Optional[str]:
    """
    Spawn blocking subprocess

    :param cmd: Command to run
    :param shell: Run ``cmd`` in a shell
    :param check: Raise ``CalledProcessError`` if ``cmd`` returns non-zero exit code
    :param timeout: Optional maximum number of seconds to wait for the command

    :return: Output (both stdout and stderr) of ``cmd``, or ``None`` if it returned a non-zero exit code

    :raise CalledProcessError: When ``check`` is true and the command fails
    :raise TimeoutExpired: When ``check`` is true and the command times out
    """
    arm_process = None
    logging.debug(f"Running command: {cmd}")
    try:
        subprocess_args = {
            "shell": shell,
            "stderr": subprocess.STDOUT,
            "encoding": "utf-8",
        }
        if timeout is not None:
            subprocess_args["timeout"] = timeout
        arm_process = subprocess.check_output(cmd, **subprocess_args)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        decoded_output: Optional[str] = None
        if isinstance(error, subprocess.CalledProcessError):
            decoded_output = error.output.strip() if error.output else None
        elif isinstance(error, subprocess.TimeoutExpired) and error.output:
            decoded_output = error.output.strip()
        logging.error(
            f"Error while running command: {cmd}\n"
            + (
                f"Output was: {decoded_output}"
                if decoded_output
                else "The command produced no output."
            ),
            exc_info=error,
        )
        if check:
            raise error

    return arm_process
