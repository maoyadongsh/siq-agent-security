package skillinstall

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func nativeInstalledFixture(t *testing.T) (fixture, *Operation) {
	t.Helper()
	if runtime.GOOS != "linux" {
		t.Skip("Linux native profile")
	}
	f := setupFiles(t, map[string]string{"references/note.txt": "\ufeffHello\r\n世界\rfinal"})
	p, _, err := f.store.Stage(nil, f.request)
	if err != nil {
		t.Fatal(err)
	}
	op, err := f.store.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, p.ActorID, true})
	if err != nil {
		t.Fatal(err)
	}
	_, err = f.store.Activate(nil, op.InstallID, ActivateRequest{"local-skill-install-activate/v1", op.Signature, p.GrantRevision, "human", true})
	if err != nil {
		t.Fatal(err)
	}
	return f, op
}
func TestNativeSourceActualApprovedInstallation(t *testing.T) {
	f, op := nativeInstalledFixture(t)
	root := "/protected/hermes/skills/example"
	for _, relative := range []string{"SKILL.md", "references/note.txt"} {
		snapshot, err := f.store.ReadNativeSource(nil, op.InstallID, f.request.InstanceID, root, hash([]byte(root+"/"+relative)))
		if err != nil {
			t.Fatal(err)
		}
		raw, err := os.ReadFile(filepath.Join(f.root, "skills", "example", filepath.FromSlash(relative)))
		if err != nil {
			t.Fatal(err)
		}
		if snapshot.InstallID != op.InstallID || snapshot.ClaimSignature != op.ClaimSignature || snapshot.Content.SHA256 != hash(raw) || snapshot.Content.Bytes != int64(len(raw)) || snapshot.HostRoot != filepath.Join(f.root, "skills", "example") {
			t.Fatal("wrong actual source")
		}
		if relative != "SKILL.md" && snapshot.TextSHA256 != hash([]byte("Hello\n世界\nfinal")) {
			t.Fatal("native decoding changed")
		}
		wire, _ := json.Marshal(snapshot)
		if bytes.Contains(wire, []byte(f.root)) || bytes.Contains(wire, raw) {
			t.Fatal("body or host path exposed")
		}
	}
}
func TestNativeSourceRejectsUntrustedOrChangedInstallation(t *testing.T) {
	for _, change := range []string{"instance", "unknown_file", "relative_root", "unclean_root", "target", "source", "revoke", "binding", "owner", "symlink", "cancelled"} {
		t.Run(change, func(t *testing.T) {
			f, op := nativeInstalledFixture(t)
			root := "/protected/hermes/skills/example"
			instance := f.request.InstanceID
			fileHash := hash([]byte(root + "/SKILL.md"))
			ctx := context.Background()
			switch change {
			case "instance":
				instance = "hi-" + strings.Repeat("a", 32)
			case "unknown_file":
				fileHash = hash([]byte(root + "/../../private.txt"))
			case "relative_root":
				root = "relative"
			case "unclean_root":
				root += "/../example"
			case "target":
				write(t, filepath.Join(f.root, "skills", "example", "SKILL.md"), "changed")
			case "source":
				write(t, filepath.Join(f.store.authority.Dir, "skill-imports", "blobs", f.importID, "payload", "SKILL.md"), "changed")
			case "revoke":
				f.revoke(t)
			case "binding":
				if err := os.Remove(f.store.bindingPath(f.request.GrantID)); err != nil {
					t.Fatal(err)
				}
			case "owner":
				write(t, filepath.Join(f.root, "skills", "example", ownerName), "{}")
			case "symlink":
				p := filepath.Join(f.root, "skills", "example", "SKILL.md")
				if err := os.Remove(p); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(filepath.Join(f.source, "SKILL.md"), p); err != nil {
					t.Fatal(err)
				}
			case "cancelled":
				var cancel context.CancelFunc
				ctx, cancel = context.WithCancel(ctx)
				cancel()
			}
			if _, err := f.store.ReadNativeSource(ctx, op.InstallID, instance, root, fileHash); err == nil {
				t.Fatal("untrusted source accepted")
			}
		})
	}
}
func TestNativeSourcePythonDecodingVectors(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/native-source-decoding.json")
	if err != nil {
		t.Fatal(err)
	}
	var rows []struct {
		InputHex string `json:"input_hex"`
		TextHex  string `json:"text_hex"`
	}
	if err = json.Unmarshal(raw, &rows); err != nil {
		t.Fatal(err)
	}
	for _, row := range rows {
		input, err := hex.DecodeString(row.InputHex)
		if err != nil {
			t.Fatal(err)
		}
		got := hex.EncodeToString(nativeDecodedText(input))
		if got != row.TextHex {
			t.Fatalf("Python decoding differs for %s: got %s want %s", row.InputHex, got, row.TextHex)
		}
	}
}
