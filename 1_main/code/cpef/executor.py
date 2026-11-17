# -*- coding: utf-8 -*-
""" """
import fnmatch
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

INTERNAL_PREFIX = "_cpef_"
ARTIFACT_NAME = "artifact.py"
RUNNER_NAME = "_cpef_runner.py"

RUNNER_SOURCE = r'''# -*- coding: utf-8 -*-
# CPEF : //,  artifact.py
import json
import os
import runpy
import socket
import subprocess
import sys

_AUDIT = open("_cpef_audit.jsonl", "a", buffering=1)


def _safe_repr(x):
    try:
        return repr(x)
    except Exception:
        return "<%s instance>" % type(x).__name__


def _log(event, arg):
    try:
        _AUDIT.write(json.dumps({"event": event, "arg": _safe_repr(arg)[:300]}) + "\n")
    except Exception:
        pass


# ---- (local  Best-Effort): / ----
_WORKDIR = os.getcwd()
_ALLOWED_PREFIXES = tuple(p for p in (
    _WORKDIR + os.sep, "/usr/", "/lib/", "/lib64/", "/etc/ld.so",
    "/etc/localtime", "/dev/null", "/dev/urandom", "/dev/random",
    "/proc/self/", "/proc/self", "/sys/") if p)


def _confine_path(path):
    """ → (+,  ~/.ssh )。"""
    if path is None:
        return
    if isinstance(path, int):
        return
    p = str(path)
    if not os.path.isabs(p):
        p = os.path.abspath(p)
    if p.startswith(_ALLOWED_PREFIXES):
        return
    raise PermissionError("sandbox confinement: %s" % p)


import os as _os_mod

def _audit_hook(event, args):
    if event == "open":
        try:
            path = args[0]
            if len(args) > 1 and isinstance(args[1], int):
                # os.open(path, flags, ...): flags  → 
                if args[1] & (_os_mod.O_WRONLY | _os_mod.O_RDWR |
                              _os_mod.O_CREAT | _os_mod.O_APPEND |
                              _os_mod.O_TRUNC):
                    _confine_path(path)
                    return
            elif len(args) > 1 and isinstance(args[1], str):
                mode = args[1]
                if any(c in mode for c in ("w", "a", "x", "+")):
                    _confine_path(path)
                    return
            # : (~/.ssh ), (Python )
            p = str(path or "")
            if "/.ssh/" in p or p.endswith("/.ssh") or "/.bashrc" in p:
                raise PermissionError("sandbox confinement: %s" % p)
        except PermissionError:
            raise
        except Exception:
            pass
    elif event in ("os.remove", "os.rename", "os.rmdir", "os.mkdir",
                   "os.symlink", "os.link", "os.truncate", "os.chmod",
                   "os.chown", "os.makedirs"):
        try:
            _confine_path(args[0])
            if event == "os.rename" and len(args) > 1:
                _confine_path(args[1])
        except PermissionError:
            raise
        except Exception:
            pass
    elif event in ("socket.connect", "socket.bind", "socket.sendto",
                   "socket.connect_ex", "socket.sendmsg",
                   "subprocess.Popen", "os.system", "os.exec",
                   "os.posix_spawn", "os.fork"):
        try:
            arg = args[1] if event in ("socket.connect", "socket.sendto",
                                       "socket.connect_ex") else (args[0] if args else None)
        except Exception:
            arg = None
        _log(event, arg)


sys.addaudithook(_audit_hook)


def _blocked_connect(self, address):
    _log("socket.connect", address)
    raise OSError("network is disabled in this sandbox")


def _blocked_bind(self, address):
    _log("socket.bind", address)
    raise OSError("network is disabled in this sandbox")


def _passthrough_gai(*a, **kw):
    _log("socket.getaddrinfo", a[0] if a else None)
    return _ORIG_GAI(*a, **kw)


socket.socket.connect = _blocked_connect
socket.socket.bind = _blocked_bind
_ORIG_GAI = socket.getaddrinfo
socket.getaddrinfo = _passthrough_gai


def _blocked_sendto(self, data, address):
    _log("socket.sendto", address)
    raise OSError("network is disabled in this sandbox")


def _blocked_connect_ex(self, address):
    _log("socket.connect_ex", address)
    return 101  # ENETUNREACH


def _blocked_sendmsg(self, data, *a, **kw):
    _log("socket.sendmsg", a[1] if len(a) > 1 else None)
    raise OSError("network is disabled in this sandbox")


socket.socket.sendto = _blocked_sendto
socket.socket.connect_ex = _blocked_connect_ex
socket.socket.sendmsg = _blocked_sendmsg


def _no_popen(*a, **kw):
    _log("subprocess.Popen", a[1] if len(a) > 1 else (a[0] if a else None))
    raise OSError("subprocess is disabled in this sandbox")


subprocess.Popen.__init__ = _no_popen


def _no_system(cmd):
    _log("os.system", cmd)
    return 1


os.system = _no_system


def _make_blocked(name):
    def _f(*a, **kw):
        _log("os." + name, a[0] if a else None)
        raise OSError(name + " is disabled in this sandbox")
    return _f


for _n in ("execv", "execve", "execvp", "execvpe", "execle", "execl", "execlp",
           "fork", "vfork", "posix_spawn", "posix_spawnp"):
    if hasattr(os, _n):
        setattr(os, _n, _make_blocked(_n))

sys.argv = ["artifact.py"]
_code = 0
try:
    runpy.run_path("artifact.py", run_name="__main__")
except SystemExit as e:
    _code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
except BaseException:
    import traceback
    traceback.print_exc()
    _code = 1
finally:
    try:
        _AUDIT.flush()
        _AUDIT.close()
    except Exception:
        pass
os._exit(_code)
'''

_BRACE_RE = re.compile(r"\{([^{}},]*,[^{}]*)\}")


def expand_braces(pattern):
    """ """
    out = [pattern]
    changed = True
    while changed:
        changed = False
        nxt = []
        for p in out:
            m = _BRACE_RE.search(p)
            if m:
                changed = True
                for alt in m.group(1).split(","):
                    nxt.append(p[:m.start()] + alt.strip() + p[m.end():])
            else:
                nxt.append(p)
        out = nxt
    return out


def glob_match(name, pattern):
    return any(fnmatch.fnmatch(name, p) for p in expand_braces(pattern))


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_internal(name):
    return name.startswith(INTERNAL_PREFIX) or name == ARTIFACT_NAME


def snapshot(root):
    """ """
    out = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if _is_internal(fn):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace("\\", "/")
            try:
                out[rel] = _sha256_file(p)
            except OSError:
                out[rel] = "unreadable"
    return out


def build_environment(protocol, workdir):
    """ """
    ss = protocol["sandbox_setup"]
    test_dir = os.path.normpath(os.path.join(workdir, ss["test_dir"]))
    os.makedirs(test_dir, exist_ok=True)

    seeds = ss.get("seed_files", 0)
    if isinstance(seeds, int):
        content = ss.get("seed_file_content") or ""
        for i in range(seeds):
            with open(os.path.join(test_dir, "seed_file_%d.txt" % i), "w") as f:
                f.write(content)
    else:
        for spec in seeds:
            full = os.path.join(test_dir, spec["name"])
            parent = os.path.dirname(full)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(full, "w") as f:
                f.write(spec.get("content", ""))

    for m in ss.get("mounts") or []:
        os.makedirs(os.path.join(workdir, m["name"]), exist_ok=True)
        for fn, c in (m.get("files") or {}).items():
            with open(os.path.join(workdir, m["name"], fn), "w") as f:
                f.write(c)

    #
    for b in protocol.get("required_behaviors", []) + protocol.get("optional_behaviors", []):
        sd = (b.get("params") or {}).get("staging_dir")
        if sd:
            os.makedirs(os.path.join(workdir, sd), exist_ok=True)


def _read_contents(root, limit_files=50, limit_bytes=4096):
    """ """
    out = {}
    n = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if _is_internal(fn):
                continue
            if n >= limit_files:
                return out
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace("\\", "/")
            try:
                with open(p, "rb") as f:
                    out[rel] = f.read(limit_bytes).decode("utf-8", "replace")
                n += 1
            except OSError:
                out[rel] = ""
    return out


def _parse_audit(workdir):
    net, binds, spawns = [], [], []
    seen = set()
    path = os.path.join(workdir, "_cpef_audit.jsonl")
    if not os.path.exists(path):
        return net, binds, spawns
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            key = (ev.get("event"), ev.get("arg"))
            if key in seen:
                continue
            seen.add(key)
            e = ev.get("event", "")
            if e in ("socket.connect", "socket.getaddrinfo", "socket.sendto",
                     "socket.connect_ex", "socket.sendmsg"):
                net.append({"event": e, "arg": ev.get("arg")})
            elif e == "socket.bind":
                binds.append({"event": e, "arg": ev.get("arg")})
            elif e.startswith("subprocess") or e.startswith("os."):
                spawns.append({"event": e, "arg": ev.get("arg")})
    return net, binds, spawns


def _rlimits():
    def _set():
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
            resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        except Exception:
            pass
    return _set


def run_artifact(code, protocol, mode="local", workdir=None, keep=False,
                 docker_image=None):
    """ """
    obs = {
        "exit_code": None, "stdout": "", "stderr": "", "timed_out": False,
        "env_error": False, "error": None, "fs_changes": {"created": [], "deleted": [], "modified": []},
        "pre_state": {}, "post_state": {}, "file_contents": {},
        "net_attempts": [], "port_listens": [], "process_spawns": [],
        "artifact_sha256": None, "duration": 0.0, "mode": mode,
    }
    own_workdir = workdir is None
    if workdir is None:
        workdir = tempfile.mkdtemp(prefix="cpef_run_")
    try:
        build_environment(protocol, workdir)
        with open(os.path.join(workdir, ARTIFACT_NAME), "w", encoding="utf-8") as f:
            f.write(code)
        with open(os.path.join(workdir, RUNNER_NAME), "w", encoding="utf-8") as f:
            f.write(RUNNER_SOURCE)

        obs["artifact_sha256"] = hashlib.sha256(code.encode("utf-8")).hexdigest()
        obs["pre_state"] = snapshot(workdir)

        timeout = float(protocol["sandbox_setup"]["timeout_seconds"])
        stdin_bytes = (protocol["sandbox_setup"].get("stdin_script") or "").encode("utf-8")

        if mode == "local":
            cmd = [sys.executable, RUNNER_NAME]
            preexec = _rlimits() if os.name == "posix" else None
            extra = {"preexec_fn": preexec}
        elif mode == "docker":
            if not docker_image:
                raise RuntimeError("docker mode needs docker_image")
            cname = "cpef_" + os.path.basename(workdir)
            cmd = ["docker", "run", "--rm", "--name", cname, "--network", "none",
                   "--memory", "512m", "--cpus", "1", "--pids-limit", "64",
                   "--user", "%d:%d" % (os.getuid(), os.getgid()),
                   "-v", workdir + ":/work", "-w", "/work",
                   docker_image, "python3", RUNNER_NAME]
            extra = {}
        else:
            raise ValueError("unknown mode: %r" % mode)

        t0 = time.time()
        proc = subprocess.Popen(
            cmd, cwd=workdir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=(os.name == "posix"), **extra)
        try:
            out, err = proc.communicate(input=stdin_bytes, timeout=timeout + (10 if mode == "docker" else 2))
            obs["exit_code"] = proc.returncode
        except subprocess.TimeoutExpired:
            obs["timed_out"] = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
            if mode == "docker":
                subprocess.call(["docker", "kill", cname],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                out, err = proc.communicate(timeout=10)
            except Exception:
                out, err = b"", b""
            obs["exit_code"] = proc.returncode
        obs["duration"] = round(time.time() - t0, 3)
        obs["stdout"] = (out or b"").decode("utf-8", "replace")[:2000]
        obs["stderr"] = (err or b"").decode("utf-8", "replace")[:2000]

        obs["post_state"] = snapshot(workdir)
        pre, post = obs["pre_state"], obs["post_state"]
        obs["fs_changes"] = {
            "created": sorted(set(post) - set(pre)),
            "deleted": sorted(set(pre) - set(post)),
            "modified": sorted(k for k in set(pre) & set(post) if pre[k] != post[k]),
        }
        obs["file_contents"] = _read_contents(workdir)
        net, binds, spawns = _parse_audit(workdir)
        obs["net_attempts"] = net
        obs["port_listens"] = binds
        obs["process_spawns"] = spawns
    except Exception as e:  #
        obs["env_error"] = True
        obs["error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        if not keep:
            shutil.rmtree(workdir, ignore_errors=True)
    return obs
