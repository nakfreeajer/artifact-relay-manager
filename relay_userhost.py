"""Per-user process host for the existing Artifact Relay Project Supervisor."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable

import project_registry
import project_supervisor


class UserHostError(Exception):
    """Sanitized launcher configuration or lifecycle error."""


CONFIG_KEYS = {
    "schemaVersion", "pythonExecutable", "supervisorScript", "workingDirectory",
    "registryPath", "oauthClientFile", "logPath", "lockPath", "workerLockPath",
    "stopPath",
    "intervalSeconds", "maxCycles", "stopTimeoutSeconds", "logMaxBytes", "logBackups",
}
MAX_CONFIG_BYTES = 16384
MAX_OUTPUT_LINE_BYTES = 8192
MAX_LOG_BYTES = 1024 * 1024
MAX_LOG_BACKUPS = 5
_SAFE_RESULTS = {"OK", "DEGRADED", "IDLE", "STOPPED", "ALREADY_RUNNING"}
_SAFE_ERRORS = {
    "AUTH_UNAVAILABLE", "PROJECT_UNAVAILABLE", "PROJECT_ERROR", "REGISTRY_INVALID",
    "CHILD_ERROR", "OUTPUT_SUPPRESSED",
}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate launcher configuration key")
        result[key] = value
    return result


def _local_absolute(value: Any, label: str) -> Path:
    if (not isinstance(value, str) or not value or len(value) > 32767
            or any(ord(ch) < 32 for ch in value) or value.startswith(("\\\\", "//"))):
        raise UserHostError(f"{label} path is invalid")
    path = Path(value)
    if not path.is_absolute():
        raise UserHostError(f"{label} path must be absolute")
    return path


def _canonical_existing_file(value: Any, label: str) -> Path:
    path = _local_absolute(value, label)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise UserHostError(f"{label} file is unavailable") from None
    if (os.path.normcase(os.path.normpath(str(path))) != os.path.normcase(os.path.normpath(str(resolved)))
            or not resolved.is_file()):
        raise UserHostError(f"{label} path is not a canonical local file")
    return resolved


def _canonical_existing_directory(value: Any, label: str) -> Path:
    path = _local_absolute(value, label)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise UserHostError(f"{label} directory is unavailable") from None
    if (os.path.normcase(os.path.normpath(str(path))) != os.path.normcase(os.path.normpath(str(resolved)))
            or not resolved.is_dir()):
        raise UserHostError(f"{label} path is not a canonical local directory")
    return resolved


def _new_file_path(value: Any, label: str) -> Path:
    path = _local_absolute(value, label)
    parent = _canonical_existing_directory(str(path.parent), f"{label} parent")
    candidate = parent / path.name
    if os.path.normcase(os.path.normpath(str(path))) != os.path.normcase(os.path.normpath(str(candidate))):
        raise UserHostError(f"{label} path is not canonical")
    if path.exists():
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            raise UserHostError(f"{label} path is unavailable") from None
        if (os.path.normcase(os.path.normpath(str(path)))
                != os.path.normcase(os.path.normpath(str(resolved))) or not resolved.is_file()):
            raise UserHostError(f"{label} path is not a canonical local file")
        return resolved
    return candidate


@dataclass(frozen=True)
class UserHostConfig:
    path: Path
    python_executable: Path
    supervisor_script: Path
    working_directory: Path
    registry_path: Path
    oauth_client_file: Path
    log_path: Path
    lock_path: Path
    worker_lock_path: Path
    stop_path: Path
    interval_seconds: int
    max_cycles: int | None
    stop_timeout_seconds: int
    log_max_bytes: int
    log_backups: int


def load_config(path: Path, *, stop_only: bool = False) -> UserHostConfig:
    try:
        config_path = Path(path)
        if not config_path.is_absolute() or not config_path.is_file():
            raise UserHostError("launcher configuration is unavailable")
        resolved_config = config_path.resolve(strict=True)
        if (os.path.normcase(os.path.normpath(str(config_path)))
                != os.path.normcase(os.path.normpath(str(resolved_config)))):
            raise UserHostError("launcher configuration path is not canonical")
        with resolved_config.open("rb") as stream:
            raw = stream.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            raise UserHostError("launcher configuration exceeds its size limit")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except UserHostError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise UserHostError("launcher configuration is invalid") from None

    if (not isinstance(value, dict) or set(value) != CONFIG_KEYS
            or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1):
        raise UserHostError("launcher configuration schema is invalid")

    interval = value["intervalSeconds"]
    cycles = value["maxCycles"]
    timeout = value["stopTimeoutSeconds"]
    log_bytes = value["logMaxBytes"]
    backups = value["logBackups"]
    if type(interval) is not int or not project_supervisor.MIN_INTERVAL_SECONDS <= interval <= project_supervisor.MAX_INTERVAL_SECONDS:
        raise UserHostError("launcher interval is invalid")
    if cycles is not None and (type(cycles) is not int or not 1 <= cycles <= project_supervisor.MAX_CYCLES):
        raise UserHostError("launcher cycle limit is invalid")
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise UserHostError("launcher stop timeout is invalid")
    if type(log_bytes) is not int or not 1024 <= log_bytes <= MAX_LOG_BYTES:
        raise UserHostError("launcher log bound is invalid")
    if type(backups) is not int or not 0 <= backups <= MAX_LOG_BACKUPS:
        raise UserHostError("launcher log backup count is invalid")

    lock_path = _new_file_path(value["lockPath"], "launcher lock")
    worker_lock_path = _new_file_path(value["workerLockPath"], "worker lock")
    stop_path = _new_file_path(value["stopPath"], "launcher stop request")
    log_path = _new_file_path(value["logPath"], "launcher log")
    controls = (lock_path, worker_lock_path, stop_path, log_path)
    if len({os.path.normcase(str(p)) for p in controls}) != len(controls):
        raise UserHostError("launcher control and log paths must be distinct")

    registry_document = None
    if stop_only:
        python_file = _local_absolute(value["pythonExecutable"], "Python executable")
        script_file = _local_absolute(value["supervisorScript"], "supervisor script")
        working_directory = _local_absolute(value["workingDirectory"], "working directory")
        registry_path = _local_absolute(value["registryPath"], "project registry")
        oauth_client_file = _local_absolute(value["oauthClientFile"], "OAuth client")
    else:
        python_file = _canonical_existing_file(value["pythonExecutable"], "Python executable")
        script_file = _canonical_existing_file(value["supervisorScript"], "supervisor script")
        if script_file.name.casefold() != "relay_supervisor.py":
            raise UserHostError("supervisor script must be relay_supervisor.py")
        if Path(project_supervisor.__file__).resolve().parent != script_file.parent:
            raise UserHostError("supervisor script does not match the imported supervisor module")
        working_directory = _canonical_existing_directory(value["workingDirectory"], "working directory")
        registry_path = _canonical_existing_file(value["registryPath"], "project registry")
        oauth_client_file = _canonical_existing_file(value["oauthClientFile"], "OAuth client")
        try:
            registry_document = project_registry.ProjectRegistry(registry_path).load()
        except Exception:
            raise UserHostError("configured project registry is invalid") from None

    protected_paths = [resolved_config, python_file, script_file, registry_path, oauth_client_file]
    if registry_document is not None:
        for entry in registry_document["projects"]:
            protected_paths.extend((Path(entry["configPath"]), Path(entry["statePath"])))
    log_paths = [log_path] + [log_path.with_name(log_path.name + f".{index}")
                              for index in range(1, backups + 1)]
    all_paths = protected_paths + [lock_path, worker_lock_path, stop_path] + log_paths
    keys = []
    for item in all_paths:
        if item.exists():
            try:
                resolved_item = item.resolve(strict=True)
            except (OSError, RuntimeError, ValueError):
                raise UserHostError("launcher output path is unavailable") from None
            if os.path.normcase(os.path.normpath(str(item))) != os.path.normcase(os.path.normpath(str(resolved_item))):
                raise UserHostError("launcher output path is not canonical")
        keys.append(os.path.normcase(os.path.normpath(str(item))))
    if len(set(keys)) != len(keys):
        raise UserHostError("launcher control and log paths conflict with runtime files")

    return UserHostConfig(
        resolved_config, python_file, script_file, working_directory, registry_path,
        oauth_client_file, log_path, lock_path, worker_lock_path, stop_path, interval, cycles,
        timeout, log_bytes, backups,
    )


def build_child_environment(base: dict[str, str], oauth_client_file: Path) -> dict[str, str]:
    child = dict(base)
    child.pop("RELAY_GDRIVE_ACCESS_TOKEN", None)
    child["RELAY_GDRIVE_OAUTH_CLIENT_FILE"] = str(oauth_client_file)
    child["PYTHONUNBUFFERED"] = "1"
    return child


def _safe_project_record(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    record = {}
    project_id = value.get("projectId")
    if isinstance(project_id, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", project_id):
        record["projectId"] = project_id
    result = value.get("result")
    if isinstance(result, str) and result in _SAFE_RESULTS:
        record["result"] = result
    error = value.get("error")
    if isinstance(error, str):
        record["error"] = error if error in _SAFE_ERRORS else "CHILD_ERROR"
    for field in ("observed", "delivered", "deduplicated", "pending", "skipped"):
        count = value.get(field)
        if type(count) is int and 0 <= count <= 2**31 - 1:
            record[field] = count
    return record or None


def _process_is_alive(pid: int) -> bool:
    """Check a parent process without sending it a signal (Windows-safe)."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        open_process.restype = wintypes.HANDLE
        get_exit_code = kernel32.GetExitCodeProcess
        get_exit_code.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        get_exit_code.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        handle = open_process(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not get_exit_code(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            close_handle(handle)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def sanitize_supervisor_line(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return {"component": "supervisor", "result": "OUTPUT_SUPPRESSED"}
    if not isinstance(value, dict):
        return {"component": "supervisor", "result": "OUTPUT_SUPPRESSED"}
    record: dict[str, Any] = {"component": "supervisor"}
    for field in ("cycle", "enabledProjects", "retryDelaySeconds"):
        number = value.get(field)
        if type(number) is int and 0 <= number <= 2**31 - 1 and not (
                field == "cycle" and value.get("result") == "STOPPED"):
            record[field] = number
    result = value.get("result")
    if isinstance(result, str) and result in _SAFE_RESULTS:
        record["result"] = result
    error = value.get("error")
    if isinstance(error, str):
        record["error"] = error if error in _SAFE_ERRORS else "CHILD_ERROR"
    projects = value.get("projects")
    if isinstance(projects, list):
        record["projects"] = [item for item in (_safe_project_record(p) for p in projects[:100]) if item]
    if len(record) == 1:
        return {"component": "supervisor", "result": "OUTPUT_SUPPRESSED"}
    return record


class BoundedJsonlLog:
    def __init__(self, path: Path, max_bytes: int, backups: int, emit: Callable[[dict], None]):
        self.path = path
        self.max_bytes = max_bytes
        self.backups = backups
        self.emit = emit
        self._lock = threading.Lock()

    def _rotate(self) -> None:
        if self.backups == 0:
            self.path.write_bytes(b"")
            return
        oldest = self.path.with_name(self.path.name + f".{self.backups}")
        if oldest.exists():
            oldest.unlink()
        for index in range(self.backups - 1, 0, -1):
            source = self.path.with_name(self.path.name + f".{index}")
            if source.exists():
                source.replace(self.path.with_name(self.path.name + f".{index + 1}"))
        if self.path.exists():
            self.path.replace(self.path.with_name(self.path.name + ".1"))

    def write(self, record: dict) -> None:
        safe = {"time": datetime.now(timezone.utc).isoformat(), **record}
        encoded = (json.dumps(safe, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > self.max_bytes:
            encoded = (json.dumps({"time": safe["time"], "component": "launcher",
                                   "result": "LOG_RECORD_SUPPRESSED"}, separators=(",", ":")) + "\n").encode("utf-8")
            safe = {"component": "launcher", "result": "LOG_RECORD_SUPPRESSED"}
        with self._lock:
            try:
                current_size = self.path.stat().st_size if self.path.exists() else 0
                if current_size + len(encoded) > self.max_bytes:
                    self._rotate()
                with self.path.open("ab") as stream:
                    stream.write(encoded)
                    stream.flush()
            except OSError:
                self.emit({"component": "launcher", "result": "LOG_WRITE_FAILED"})
                return
            self.emit(safe)


class SingleInstanceLock:
    """OS-released byte lock; the file may remain after exit and is not a PID authority."""

    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def acquire(self, *, blocking: bool = False) -> bool:
        try:
            self.stream = self.path.open("a+b")
            if os.name == "nt":
                import msvcrt
                self.stream.seek(0)
                if self.path.stat().st_size == 0:
                    self.stream.write(b"\0")
                    self.stream.flush()
                    self.stream.seek(0)
                mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
                msvcrt.locking(self.stream.fileno(), mode, 1)
            else:
                import fcntl
                mode = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
                fcntl.flock(self.stream.fileno(), mode)
            return True
        except (OSError, BlockingIOError):
            if self.stream is not None:
                self.stream.close()
                self.stream = None
            return False

    def release(self) -> None:
        if self.stream is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self.stream.close()
            self.stream = None

    def __enter__(self):
        if not self.acquire():
            raise UserHostError("another launcher instance is already running")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()


def _write_stop_request(path: Path) -> None:
    fd = None
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix=".userhost-stop-", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            fd = None
            stream.write("stop\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except OSError:
        raise UserHostError("could not request launcher stop") from None
    finally:
        if fd is not None:
            os.close(fd)
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _worker(config_path: Path, max_cycles_override: int | None, parent_pid: int) -> int:
    try:
        config = load_config(config_path)
    except UserHostError:
        print(json.dumps({"component": "supervisor", "error": "REGISTRY_INVALID"}), flush=True)
        return 2
    worker_lock = SingleInstanceLock(config.worker_lock_path)
    if not worker_lock.acquire():
        print(json.dumps({"component": "supervisor", "result": "ALREADY_RUNNING"}), flush=True)
        return 3
    stop_event = threading.Event()

    def watch_stop_file():
        while not stop_event.is_set():
            try:
                if config.stop_path.exists():
                    stop_event.set()
                    return
            except OSError:
                stop_event.set()
                return
            if not _process_is_alive(parent_pid):
                stop_event.set()
                return
            stop_event.wait(0.1)

    def worker_emit(record: dict) -> None:
        try:
            print(json.dumps(record, sort_keys=True, separators=(",", ":")), flush=True)
        except (BrokenPipeError, OSError):
            stop_event.set()

    watcher = threading.Thread(target=watch_stop_file, name="relay-userhost-stop", daemon=True)
    watcher.start()
    max_cycles = max_cycles_override if max_cycles_override is not None else config.max_cycles

    def interruptible_sleep(delay: float) -> None:
        if stop_event.wait(delay):
            raise KeyboardInterrupt

    try:
        if stop_event.is_set():
            worker_emit({"cycle": 0, "result": "STOPPED"})
            return 0
        return project_supervisor.run_supervisor(
            config.registry_path,
            interval_seconds=config.interval_seconds,
            max_cycles=max_cycles,
            sleeper=interruptible_sleep,
            emit=worker_emit,
        )
    except Exception:
        worker_emit({"component": "supervisor", "error": "CHILD_ERROR"})
        return 2
    finally:
        stop_event.set()
        watcher.join(timeout=1)
        worker_lock.release()


def _stream_child(stream: BinaryIO, *, is_stderr: bool, log: BoundedJsonlLog) -> None:
    suppressed_bytes = 0
    while True:
        raw = stream.readline(MAX_OUTPUT_LINE_BYTES + 1)
        if not raw:
            break
        if len(raw) > MAX_OUTPUT_LINE_BYTES and not raw.endswith(b"\n"):
            suppressed_bytes += len(raw)
            while True:
                tail = stream.readline(MAX_OUTPUT_LINE_BYTES + 1)
                suppressed_bytes += len(tail)
                if not tail or tail.endswith(b"\n"):
                    break
            if not is_stderr:
                log.write({"component": "supervisor", "result": "OUTPUT_SUPPRESSED"})
            continue
        if is_stderr:
            suppressed_bytes += len(raw)
        else:
            log.write(sanitize_supervisor_line(raw.strip()))
    if is_stderr and suppressed_bytes:
        log.write({"component": "supervisor", "stream": "stderr", "result": "OUTPUT_SUPPRESSED",
                   "byteLength": min(suppressed_bytes, 2**31 - 1)})


def _validate_dry_run(registry: dict, max_cycles: int | None) -> None:
    if max_cycles is None:
        raise UserHostError("dry-run requires an explicit bounded cycle count")
    projects = registry.get("projects", [])
    if any(item.get("enabled") is True for item in projects if isinstance(item, dict)):
        raise UserHostError("dry-run requires every configured project to be disabled")


def start(config_path: Path, *, max_cycles: int | None = None, dry_run: bool = False,
          emit: Callable[[dict], None] | None = None) -> int:
    if max_cycles is not None and (type(max_cycles) is not int or not 1 <= max_cycles <= project_supervisor.MAX_CYCLES):
        raise UserHostError("cycle limit is invalid")
    config = load_config(config_path)
    registry = project_registry.ProjectRegistry(config.registry_path).load()
    if dry_run:
        _validate_dry_run(registry, max_cycles)
    output = emit if emit is not None else print_json
    logger = BoundedJsonlLog(config.log_path, config.log_max_bytes, config.log_backups, output)

    lock = SingleInstanceLock(config.lock_path)
    if not lock.acquire():
        output({"component": "launcher", "result": "ALREADY_RUNNING"})
        return 3

    process: subprocess.Popen | None = None
    try:
        try:
            config.stop_path.unlink(missing_ok=True)
        except OSError:
            logger.write({"component": "launcher", "result": "STOP_PATH_UNAVAILABLE"})
            return 2
        env = build_child_environment(os.environ, config.oauth_client_file)
        command = [
            str(config.python_executable), str(Path(__file__).resolve()),
            "--config", str(config.path), "_worker",
            "--parent-pid", str(os.getpid()),
        ]
        effective_cycles = max_cycles if max_cycles is not None else config.max_cycles
        if effective_cycles is not None:
            command.extend(("--max-cycles", str(effective_cycles)))
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        logger.write({"component": "launcher", "result": "STARTING", "mode": "DRY_RUN" if dry_run else "RUN"})
        try:
            process = subprocess.Popen(
                command, cwd=str(config.working_directory), env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=creationflags, close_fds=True,
            )
        except OSError:
            logger.write({"component": "launcher", "result": "SPAWN_FAILED"})
            return 2

        assert process.stdout is not None and process.stderr is not None
        stdout_thread = threading.Thread(target=_stream_child, args=(process.stdout,),
                                         kwargs={"is_stderr": False, "log": logger}, daemon=True)
        stderr_thread = threading.Thread(target=_stream_child, args=(process.stderr,),
                                         kwargs={"is_stderr": True, "log": logger}, daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        stop_deadline: float | None = None
        while process.poll() is None:
            if config.stop_path.exists() and stop_deadline is None:
                logger.write({"component": "launcher", "result": "STOP_REQUESTED"})
                stop_deadline = time.monotonic() + config.stop_timeout_seconds
            if stop_deadline is not None and time.monotonic() >= stop_deadline and process.poll() is None:
                logger.write({"component": "launcher", "result": "STOP_TIMEOUT", "childAction": "TERMINATE_OWNED_CHILD"})
                process.terminate()
                break
            try:
                process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                continue
            except KeyboardInterrupt:
                if stop_deadline is None:
                    _write_stop_request(config.stop_path)
                    stop_deadline = time.monotonic() + config.stop_timeout_seconds
        return_code = process.wait()
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        if return_code == 0:
            logger.write({"component": "launcher", "result": "STOPPED" if stop_deadline is not None else "EXITED",
                          "exitCode": return_code})
            return 0
        logger.write({"component": "launcher", "result": "CHILD_FAILED", "exitCode": return_code})
        return return_code if 1 <= return_code <= 125 else 2
    finally:
        try:
            config.stop_path.unlink(missing_ok=True)
        except OSError:
            pass
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        lock.release()


def stop(config_path: Path, *, emit: Callable[[dict], None] | None = None) -> int:
    config = load_config(config_path, stop_only=True)
    output = emit if emit is not None else print_json
    parent_busy = _lock_is_held(config.lock_path)
    worker_busy = _lock_is_held(config.worker_lock_path)
    if not parent_busy and not worker_busy:
        output({"component": "launcher", "result": "NOT_RUNNING"})
        return 1
    try:
        _write_stop_request(config.stop_path)
    except UserHostError:
        output({"component": "launcher", "result": "STOP_REQUEST_FAILED"})
        return 2
    deadline = time.monotonic() + config.stop_timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(0.1)
        if not _lock_is_held(config.lock_path) and not _lock_is_held(config.worker_lock_path):
            output({"component": "launcher", "result": "STOPPED"})
            return 0
    output({"component": "launcher", "result": "STOP_TIMEOUT"})
    return 2


def _lock_is_held(path: Path) -> bool:
    probe = SingleInstanceLock(path)
    if probe.acquire():
        probe.release()
        return False
    return True


def print_json(record: dict) -> None:
    try:
        print(json.dumps(record, sort_keys=True, separators=(",", ":")), flush=True)
    except (OSError, AttributeError):
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="absolute local userhost.json path")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("start")
    run.add_argument("--max-cycles", type=int)
    run.add_argument("--dry-run", action="store_true")
    commands.add_parser("stop")
    worker = commands.add_parser("_worker")
    worker.add_argument("--max-cycles", type=int)
    worker.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if not args.config.is_absolute():
            raise UserHostError("launcher configuration path must be absolute")
        if args.command == "start":
            return start(args.config, max_cycles=args.max_cycles, dry_run=args.dry_run)
        if args.command == "stop":
            return stop(args.config)
        return _worker(args.config, args.max_cycles, args.parent_pid)
    except UserHostError as exc:
        print_json({"component": "launcher", "result": "BLOCKED", "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
