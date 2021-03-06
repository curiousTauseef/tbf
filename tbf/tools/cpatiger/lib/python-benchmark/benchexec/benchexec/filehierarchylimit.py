# BenchExec is a framework for reliable benchmarking.
# This file is part of BenchExec.
#
# Copyright (C) 2007-2017  Dirk Beyer
# All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# prepare for Python 3
from __future__ import absolute_import, division, print_function, unicode_literals

# THIS MODULE HAS TO WORK WITH PYTHON 2.7!

import logging
import os
import threading

from benchexec import container
from benchexec import util

_CHECK_INTERVAL_SECONDS = 60
_DURATION_WARNING_THRESHOLD = 1


class FileHierarchyLimitThread(threading.Thread):
    """
    Thread that periodically checks whether a given file hierarchy exceeds some limits.
    After this happens, the process is terminated.
    """

    def __init__(self,
                 path,
                 files_count_limit,
                 files_size_limit,
                 kill_process_fn,
                 pid_to_kill,
                 cgroups,
                 callbackFn=lambda reason: None):
        super(FileHierarchyLimitThread, self).__init__()
        self.name = "FileHierarchyLimitThread-" + self.name

        assert os.path.isdir(path)
        self._path = path
        self._files_count_limit = files_count_limit
        self._files_size_limit = files_size_limit

        self._kill_process = kill_process_fn
        self._pid_to_kill = pid_to_kill
        self._cgroups = cgroups
        self._callback = callbackFn
        self._finished = threading.Event()

    def _check_limit(self, files_count, files_size):
        if self._files_count_limit and files_count > self._files_count_limit:
            reason = "files-count"
        elif self._files_size_limit and files_size > self._files_size_limit:
            reason = "files-size"
        else:
            return None
        self._callback(reason)
        logging.debug(
            'Killing process %d due to %s limit (%d files with %d bytes).',
            self._pid_to_kill, reason, files_count, files_size)
        self._kill_process(self._pid_to_kill, self._cgroups)
        return reason

    def run(self):
        while not self._finished.is_set():
            self._finished.wait(_CHECK_INTERVAL_SECONDS)

            files_count = 0
            files_size = 0
            start_time = util.read_monotonic_time()
            for current_dir, dirs, files in os.walk(self._path):
                for file in files:
                    abs_file = os.path.join(current_dir, file)
                    file = '/' + os.path.relpath(
                        file, self._path)  # as visible for tool
                    if (not container.is_container_system_config_file(file) and
                            os.path.isfile(abs_file) and
                            not os.path.islink(abs_file)):
                        files_count += 1
                        if self._files_size_limit:
                            try:
                                files_size += os.path.getsize(abs_file)
                            except OSError:
                                # possibly just deleted
                                pass
            if self._check_limit(files_count, files_size):
                return

            duration = util.read_monotonic_time() - start_time

            logging.debug(
                "FileHierarchyLimitThread for process %d: "
                "files count: %d, files size: %d, scan duration %fs",
                self._pid_to_kill, files_count, files_size, duration)
            if duration > _DURATION_WARNING_THRESHOLD:
                logging.warning(
                    "Scanning file hierarchy for enforcement of limits took %ds.",
                    duration)

    def cancel(self):
        self._finished.set()
