"""Owned OpenShell image-profile component probe; no model or business claims."""

import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

from build_native_overlay import IMAGE

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "adapters/runtime/hermes-agentshield"
RUNTIME = "/opt/siq/native-profile-probe"
PYTHON = "/opt/siq/hermes/venv/bin/python"
BOOTSTRAP = '''import importlib.util,json,os,pathlib,socket,stat,threading,time
spec=importlib.util.spec_from_file_location('native_channel','/opt/siq/native-profile-probe/native_channel.py')
channel=importlib.util.module_from_spec(spec)
spec.loader.exec_module(channel)
directory=pathlib.Path('/tmp/siq-native-profile-'+str(os.getpid()))
directory.mkdir(mode=0o700)
status={}
for line in open('/proc/self/status'):
    key,_,value=line.partition(':')
    if key in ('Uid','Gid','NSpid','CapEff','CapPrm','CapAmb','NoNewPrivs','Seccomp'):
        status[key]=value.split()
files=[]
for path in ['/opt/siq/native-profile-probe/bootstrap.py','/opt/siq/native-profile-probe/native_channel.py']:
    info=os.stat(path)
    denied=None
    try:
        fd=os.open(path,os.O_WRONLY)
        os.close(fd)
    except OSError as error:
        denied=error.errno
    files.append({'path':path,'uid':info.st_uid,'gid':info.st_gid,'mode':stat.S_IMODE(info.st_mode),'write_open_errno':denied})
print(json.dumps({'native_probe_ready':True,'pid':os.getpid(),'status':status,'files':files,'channel_directory':str(directory)}),flush=True)
path=directory/'native-host.sock'
deadline=time.monotonic()+30
while not path.exists():
    if time.monotonic()>=deadline: raise SystemExit(2)
    time.sleep(.05)
result=channel.HermesChannel(path,timeout=5,server_credentials=(0,os.getuid(),os.getgid())).exchange({'kind':'image-profile-probe'})
assert result=={'accepted':True}
# An actual same-container server must not be mistaken for the outer host.
fake=directory/'fake.sock'
listener=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET)
listener.bind(str(fake)); listener.listen(1); listener.settimeout(5)
def impersonate():
    connection,_=listener.accept()
    with connection:
        request=json.loads(connection.recv(65536))
        connection.send(json.dumps({'schema_version':'native-host-response/v1','sequence':request['sequence'],'result':{'accepted':True}}).encode())
thread=threading.Thread(target=impersonate)
thread.start()
rejected=False
try:
    channel.HermesChannel(fake,timeout=5,server_credentials=(0,os.getuid(),os.getgid())).exchange({})
except channel.ChannelError:
    rejected=True
thread.join(timeout=6); listener.close()
assert rejected and not thread.is_alive()
print(json.dumps({'native_channel_verified':True,'same_namespace_imposter_rejected':rejected}),flush=True)
time.sleep(40)
'''


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def prepare(output, command):
    context = output / "image-context"
    context.mkdir(mode=0o700)
    files = {"native_channel.py": (ADAPTER / "native_channel.py").read_bytes(),
             "bootstrap.py": BOOTSTRAP.encode(), "skill/SKILL.md": b"Synthetic image-profile probe skill.\n"}
    for name, raw in files.items():
        path = context / name
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o644)
    (context / "Dockerfile").write_text(
        f"FROM {IMAGE}\nUSER root\nCOPY --chown=0:0 native_channel.py bootstrap.py {RUNTIME}/\n"
        f"COPY --chown=0:0 skill/SKILL.md {RUNTIME}/skill/SKILL.md\n"
        f"RUN chmod 0555 {RUNTIME} {RUNTIME}/skill && chmod 0444 {RUNTIME}/*.py {RUNTIME}/skill/SKILL.md\nUSER sandbox\n")
    iid = output / "image-id"
    command(["/usr/bin/docker", "build", "--network=none", "--pull=false", "--iidfile", str(iid), str(context)], timeout=60)
    image = iid.read_text().strip()
    assert image.startswith("sha256:") and len(image) == 71
    # Independent baseline from the fixed base image, not the observed peer.
    extractor = output / "extractor-id"
    try:
        executable = command(["/usr/bin/docker", "run", "--rm", "--pull=never", "--network=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
            "--cidfile", str(extractor), "--entrypoint", PYTHON, IMAGE, "-I", "-B", "-c",
            "import hashlib; print(hashlib.sha256(open('/proc/self/exe','rb').read()).hexdigest())"]).stdout.decode().strip()
    finally:
        if extractor.exists():
            cid = extractor.read_text().strip()
            if len(cid) == 64 and all(c in "0123456789abcdef" for c in cid):
                command(["/usr/bin/docker", "rm", "-f", cid], required=False)
    manifest = {RUNTIME + "/" + name: digest(raw) for name, raw in files.items()}
    artifact = digest(json.dumps({"image": image, "files": manifest, "executable": executable}, sort_keys=True).encode())
    return {"image": image, "files": manifest, "artifact": artifact, "executable": executable,
            "argv": [PYTHON, "-I", "-B", RUNTIME + "/bootstrap.py"], "skill_source": str(context / "skill")}


def runtime_options(prepared, *, peer, cid, namespace, sandbox, init_pid, init_groups, command):
    spec = importlib.util.spec_from_file_location("siq_image_probe_guard", ADAPTER / "host_runtime.py",
                                                submodule_search_locations=[str(ADAPTER)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    channel = sys.modules[spec.name + ".native_channel"]

    def backend(pid, uid, gid, artifact):
        assert (pid, uid, gid, artifact) == (peer, os.getuid(), os.getgid(), prepared["artifact"])
        fields = ("Id", "Image", "State.Pid", "State.Running", "Config.Labels", "HostConfig.Privileged")
        raw = command(["/usr/bin/docker", "inspect", "--format", "\n".join("{{json ." + f + "}}" for f in fields), cid], timeout=2)
        actual = dict(zip(fields, map(json.loads, raw.stdout.decode().splitlines()), strict=True))
        assert actual["Id"].startswith(cid) and actual["Image"] == prepared["image"]
        assert actual["State.Pid"] == init_pid and actual["State.Running"] and not actual["HostConfig.Privileged"]
        assert actual["Config.Labels"]["openshell.ai/sandbox-namespace"] == namespace
        assert actual["Config.Labels"]["openshell.ai/sandbox-name"] == sandbox
        assert actual["Config.Labels"].get("openshell.ai/sandbox-id")
        assert Path(f"/proc/{peer}/cgroup").read_text() == init_groups

    options = {"pid": peer, "uid": os.getuid(), "gid": os.getgid(), "artifact_sha256": prepared["artifact"],
               "executable_sha256": prepared["executable"],
               "argv_sha256": digest(b"\0".join(p.encode() for p in prepared["argv"]) + b"\0"),
               "mounts": [], "code_files": {}, "verify_backend": backend, "image_files": prepared["files"],
               "image_skill_roots": prepared.get("skill_roots", [{"source": prepared.get("skill_source"), "target": RUNTIME + "/skill"}])}
    return module, channel, options


def verify(prepared, *, peer, cid, namespace, sandbox, init_pid, init_groups, row, command, exec_log):
    module, channel, options = runtime_options(prepared, peer=peer, cid=cid, namespace=namespace,
        sandbox=sandbox, init_pid=init_pid, init_groups=init_groups, command=command)
    checks = {}
    with module.RuntimeGuard(**options) as guard:
        guard.verify_mount(prepared["skill_source"], RUNTIME + "/skill")
        checks["actual_openshell_process_image_and_skill_files"] = True
        with guard.namespace_channel_directory(row["channel_directory"]) as fd:
            with channel.NamespaceHostChannel(fd, guard.peer, timeout=5) as host:
                def dispatch(event):
                    guard.verify()
                    assert event == {"kind": "image-profile-probe"}
                    return {"accepted": True}
                host.serve_once(dispatch)
            deadline = time.monotonic() + 8
            while True:
                rows = [json.loads(line) for line in exec_log.read_text(errors="replace").splitlines()
                        if line.startswith('{"native_channel_verified":')]
                if rows:
                    assert rows == [{"native_channel_verified": True, "same_namespace_imposter_rejected": True}]
                    break
                assert time.monotonic() < deadline, "runtime_client_ack_missing"
                time.sleep(.05)
            checks["bidirectional_cross_pid_namespace_channel"] = True
            checks["same_namespace_socket_imposter_rejected"] = True
    variants = {
        "wrong_code_digest": {"image_files": dict.fromkeys(prepared["files"], "0" * 64)},
        "wrong_interpreter": {"executable_sha256": "0" * 64},
        "wrong_launch_arguments": {"argv_sha256": "0" * 64},
        "wrong_artifact": {"artifact_sha256": "0" * 64},
        "undeclared_skill_file": {"image_files": {p: h for p, h in prepared["files"].items() if "/skill/" not in p}},
        "mixed_mount_profile": {"code_files": {"/synthetic": "0" * 64}},
        "missing_backend": {"verify_backend": None},
    }
    for name, change in variants.items():
        try:
            unexpected = module.RuntimeGuard(**(options | change))
        except module.RuntimeGuardError:
            checks[name + "_rejected"] = True
        else:
            unexpected.close()
            raise AssertionError("image_profile_negative_accepted:" + name)
    assert all(file["write_open_errno"] == 13 for file in row["files"])
    checks["runtime_cannot_open_protected_code_for_write"] = True
    return {"checks": checks, "image_id": prepared["image"], "artifact_sha256": prepared["artifact"],
            "files": prepared["files"], "business_acceptance": False, "model_calls": 0}
