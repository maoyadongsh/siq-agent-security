package skillcontext

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
	"siq-agent-security/apps/agentshield/internal/state"
)

func nativeResolverFixture(t *testing.T) (*NativeInstallResolver, Subject, NativeInstallMount) {
	t.Helper()
	if runtime.GOOS != "linux" {
		t.Skip("Linux native profile")
	}
	st, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	imports, err := skillimport.Open(st.Dir, key, pack, "native-source-integration")
	if err != nil {
		t.Fatal(err)
	}
	source, root := t.TempDir(), t.TempDir()
	write := func(name, body string) {
		t.Helper()
		if err := os.WriteFile(filepath.Join(source, name), []byte(body), 0600); err != nil {
			t.Fatal(err)
		}
	}
	write("SKILL.md", "---\nname: example\ndescription: Read a synthetic report.\nallowed-tools: read_file\n---\nRead a synthetic report.\n")
	write("note.txt", "\ufeffSynthetic\r\n世界\rdata")
	id := "si-" + strings.Repeat("a", 32)
	if _, _, _, err = imports.Create(nil, skillimport.CreateRequest{SchemaVersion: "local-skill-import-create/v1", ImportID: id, SourceKind: "local_dir", Path: source, ActorID: "human"}); err != nil {
		t.Fatal(err)
	}
	_, derived, err := imports.PermissionAdmission(nil, id)
	if err != nil {
		t.Fatal(err)
	}
	if err = st.PutImportAdmission(derived); err != nil {
		t.Fatal(err)
	}
	built, err := grant.BuildImported(derived.Admission, grant.Options{Key: key, Platform: "hermes", Subject: grant.Subject{Type: "agent_instance", ID: testAgent}}, "human", "ip-"+strings.Repeat("c", 32))
	if err != nil {
		t.Fatal(err)
	}
	approved, err := grant.Approve(built.Grant, grant.Approval{ActorType: "human", ActorID: "human", ApprovedAt: time.Now().UTC().Format(time.RFC3339Nano)}, key)
	if err != nil {
		t.Fatal(err)
	}
	rev, err := st.CommitGrant(state.GrantCommit{Grant: approved, ExpectedRevision: -1, DesiredPolicy: built.DesiredPolicy, Audit: &state.AuditEvent{Event: "fixture_approve", Target: approved.GrantID}})
	if err != nil {
		t.Fatal(err)
	}
	store, err := skillinstall.Open(st, key, imports, func(context.Context, string) (skillinstall.Target, error) {
		return skillinstall.Target{InstanceID: testInstance, Platform: "hermes", Root: root, Display: "Native fixture"}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	plan, _, err := store.Stage(nil, skillinstall.Request{SchemaVersion: "local-skill-install-stage-create/v1", RequestID: "is-" + strings.Repeat("d", 32), GrantID: approved.GrantID, ExpectedRevision: rev, InstanceID: testInstance, DirectoryName: "example", ActorID: "human"})
	if err != nil {
		t.Fatal(err)
	}
	op, err := store.Apply(nil, skillinstall.ApplyRequest{SchemaVersion: "local-skill-install-apply/v1", PlanID: plan.PlanID, PlanSignature: plan.Signature, ActorID: "human", ConfirmInstall: true})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = store.Activate(nil, op.InstallID, skillinstall.ActivateRequest{SchemaVersion: "local-skill-install-activate/v1", OperationSignature: op.Signature, ExpectedRevision: plan.GrantRevision, ActorID: "human", ConfirmInstanceScope: true}); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(root, "skills", "example")
	mount := NativeInstallMount{InstanceID: testInstance, InstallID: op.InstallID, ClaimSignature: op.ClaimSignature, HostRoot: target, RuntimeRoot: target}
	resolver, err := NewNativeInstallResolver(store, []NativeInstallMount{mount}, func(context.Context, Subject, NativeInstallMount) error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	return resolver, Subject{Platform: "hermes", InstanceID: testInstance, AgentID: testAgent, SessionID: testSession, TaskID: testTask}, mount
}
func nativePythonSource(t *testing.T, root, content string) NativeSource {
	t.Helper()
	python, err := exec.LookPath("python3")
	if err != nil {
		t.Skip("Python native reader not available")
	}
	module, err := filepath.Abs("../../../../adapters/runtime/hermes-agentshield/native_source.py")
	if err != nil {
		t.Fatal(err)
	}
	script := `import importlib.util,json,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("actual_native_source",sys.argv[1])
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
events=[]
reader=m.SkillSourceReader(events.append,managed_link_pair=True)
reader.read(Path(sys.argv[2])/"SKILL.md",Path(sys.argv[2])/sys.argv[3])
reader.close()
print(json.dumps(events[-1]))`
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	raw, err := exec.CommandContext(ctx, python, "-I", "-B", "-c", script, module, root, content).Output()
	if err != nil {
		t.Fatal("actual Python reader failed", err)
	}
	var source NativeSource
	if err = json.Unmarshal(raw, &source); err != nil {
		t.Fatal(err)
	}
	return source
}
func TestNativeInstallResolverActualPythonSource(t *testing.T) {
	resolver, subject, mount := nativeResolverFixture(t)
	for _, file := range []string{"SKILL.md", "note.txt"} {
		source := nativePythonSource(t, mount.RuntimeRoot, file)
		ref, err := resolver.Resolve(subject, source)
		if err != nil || ref.InstallID != mount.InstallID || ref.ClaimSignature != mount.ClaimSignature {
			t.Fatal("Python source failed real installation resolution", err)
		}
		source.CacheHit = true
		if _, err = resolver.Resolve(subject, source); err != nil {
			t.Fatal("cache bypassed actual recheck", err)
		}
		source.TextSHA256 = strings.Repeat("f", 64)
		if _, err = resolver.Resolve(subject, source); err == nil {
			t.Fatal("forged decoded hash accepted")
		}
	}
	source := nativePythonSource(t, mount.RuntimeRoot, "SKILL.md")
	resolver.verifyMount = func(context.Context, Subject, NativeInstallMount) error { return errMissing }
	if _, err := resolver.Resolve(subject, source); err == nil {
		t.Fatal("mount verification failure accepted")
	}
	resolver.verifyMount = func(context.Context, Subject, NativeInstallMount) error { return nil }
	if err := os.WriteFile(filepath.Join(mount.HostRoot, "note.txt"), []byte("unrelated installed content changed"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := resolver.Resolve(subject, source); err == nil {
		t.Fatal("matching main hid changed support file")
	}
}
func TestNativeInstallResolverRejectsAmbiguousMounts(t *testing.T) {
	resolver, subject, mount := nativeResolverFixture(t)
	verify := resolver.verifyMount
	if _, err := NewNativeInstallResolver(resolver.installs, []NativeInstallMount{mount}, nil); err == nil {
		t.Fatal("missing mount verifier accepted")
	}
	for _, root := range []string{mount.RuntimeRoot, mount.RuntimeRoot + "/nested", filepath.Dir(mount.RuntimeRoot), "relative", "/bad/../path"} {
		next := mount
		next.RuntimeRoot = root
		if _, err := NewNativeInstallResolver(resolver.installs, []NativeInstallMount{mount, next}, verify); err == nil {
			t.Fatal("ambiguous or invalid mount accepted", root)
		}
	}
	source := nativePythonSource(t, mount.RuntimeRoot, "SKILL.md")
	subject.AgentID = "hri-" + strings.Repeat("b", 32)
	if _, err := resolver.Resolve(subject, source); err == nil {
		t.Fatal("another instance borrowed source mapping")
	}
}

func TestNativeInstallResolverGatesActualPythonReturn(t *testing.T) {
	for _, deny := range []bool{false, true} {
		name := "verified"
		if deny {
			name = "mount_rejected"
		}
		t.Run(name, func(t *testing.T) {
			resolver, subject, mount := nativeResolverFixture(t)
			if deny {
				resolver.verifyMount = func(context.Context, Subject, NativeInstallMount) error { return errMissing }
			}
			python, err := exec.LookPath("python3")
			if err != nil {
				t.Skip("Python reader unavailable")
			}
			module, err := filepath.Abs("../../../../adapters/runtime/hermes-agentshield/native_source.py")
			if err != nil {
				t.Fatal(err)
			}
			script := `import importlib.util,json,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("actual_source",sys.argv[1])
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
def observe(event):
    print(json.dumps(event),flush=True)
    if sys.stdin.readline().strip()!="verified": raise RuntimeError("source_rejected")
reader=m.SkillSourceReader(observe,managed_link_pair=True)
try:
    reader.read(Path(sys.argv[2])/"SKILL.md",Path(sys.argv[2])/"note.txt")
    print("text_returned",flush=True)
except m.SourceError:
    print("text_refused",flush=True)
finally: reader.close()`
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			cmd := exec.CommandContext(ctx, python, "-I", "-B", "-c", script, module, mount.RuntimeRoot)
			input, err := cmd.StdinPipe()
			if err != nil {
				t.Fatal(err)
			}
			output, err := cmd.StdoutPipe()
			if err != nil {
				t.Fatal(err)
			}
			if err = cmd.Start(); err != nil {
				t.Fatal(err)
			}
			defer func() { input.Close(); cancel(); _ = cmd.Wait() }()
			scanner := bufio.NewScanner(output)
			if !scanner.Scan() {
				t.Fatal("native observation missing")
			}
			var source NativeSource
			if err = json.Unmarshal(scanner.Bytes(), &source); err != nil {
				t.Fatal(err)
			}
			_, verifyErr := resolver.Resolve(subject, source)
			answer := "verified\n"
			if verifyErr != nil {
				answer = "refused\n"
			}
			if _, err = input.Write([]byte(answer)); err != nil {
				t.Fatal(err)
			}
			input.Close()
			if !scanner.Scan() {
				t.Fatal("native completion missing")
			}
			want := "text_returned"
			if deny {
				want = "text_refused"
			}
			if scanner.Text() != want || (verifyErr != nil) != deny {
				t.Fatal("native reader bypassed actual Go installation observer")
			}
			if scanner.Scan() {
				t.Fatal("unexpected output")
			}
			if err = scanner.Err(); err != nil {
				t.Fatal(err)
			}
			if err = cmd.Wait(); err != nil {
				t.Fatal(err)
			}
		})
	}
}
