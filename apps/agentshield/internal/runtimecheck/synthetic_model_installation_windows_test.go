package runtimecheck

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/statefs"
)

func syntheticLauncherFixture(t *testing.T) (string, string, string) {
	t.Helper()
	root := t.TempDir()
	venv := filepath.Join(root, "venv")
	site := filepath.Join(venv, "Lib", "site-packages")
	module := "__editable___hermes_agent_0_0_finder"
	files := map[string][]byte{
		filepath.Join(venv, "Scripts", "python.exe"):             []byte("not executed"),
		filepath.Join(venv, "pyvenv.cfg"):                        []byte("include-system-site-packages = false\n"),
		filepath.Join(root, "hermes_cli", "main.py"):             []byte("# not executed\n"),
		filepath.Join(root, "hermes_cli", "env_loader.py"):       []byte("# not executed\n"),
		filepath.Join(root, "hermes_cli", "managed_scope.py"):    []byte("# not executed\n"),
		filepath.Join(site, "__editable__.hermes_agent-0.0.pth"): []byte("import " + module + "; " + module + ".install()"),
	}
	direct, _ := json.Marshal(map[string]any{"url": "file:///" + filepath.ToSlash(root), "dir_info": map[string]any{"editable": true}})
	files[filepath.Join(site, "hermes_agent-0.0.dist-info", "direct_url.json")] = direct
	mapping, _ := json.Marshal(map[string]string{"hermes_cli": filepath.Join(root, "hermes_cli")})
	finder := filepath.Join(site, module+".py")
	files[finder] = []byte("MAPPING: dict[str, str] = " + string(mapping) + "\n")
	for path, raw := range files {
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
	buf := bytes.NewBufferString("MZ")
	w := zip.NewWriter(buf)
	f, err := w.Create("__main__.py")
	if err != nil {
		t.Fatal(err)
	}
	_, err = f.Write([]byte("#!" + filepath.Join(venv, "Scripts", "python.exe") + "\n" + hermesLauncherMain))
	if err != nil {
		t.Fatal(err)
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	cli := filepath.Join(root, "hermes.exe")
	if err := os.WriteFile(cli, buf.Bytes(), 0600); err != nil {
		t.Fatal(err)
	}
	return root, cli, finder
}

func TestSyntheticInstallationRejectsUnknownOrChangedRoots(t *testing.T) {
	for _, which := range []string{"valid", "dotenv", "op-env", "wrong-mapping", "corrupt-launcher", "changed-after"} {
		t.Run(which, func(t *testing.T) {
			root, cli, finder := syntheticLauncherFixture(t)
			switch which {
			case "dotenv", "op-env":
				name := ".env"
				if which == "op-env" {
					name = ".op.env"
				}
				if err := os.WriteFile(filepath.Join(root, name), []byte("SYNTHETIC_ONLY=1"), 0600); err != nil {
					t.Fatal(err)
				}
			case "wrong-mapping":
				if err := os.WriteFile(finder, []byte("MAPPING: dict[str, str] = {'hermes_cli': 'unknown'}\n"), 0600); err != nil {
					t.Fatal(err)
				}
			case "corrupt-launcher":
				if err := os.WriteFile(cli, []byte("MZ unknown"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			pins, err := inspectSyntheticInstallation(cli)
			if which != "valid" && which != "changed-after" {
				if err == nil {
					t.Fatal("unverified installation accepted")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if which == "changed-after" {
				if err := os.WriteFile(filepath.Join(root, ".env"), []byte("SYNTHETIC_ONLY=1"), 0600); err != nil {
					t.Fatal(err)
				}
				bad := false
				for _, pin := range pins {
					bad = bad || pin.verify() != nil
				}
				if !bad {
					t.Fatal("late installation dotenv accepted")
				}
			}
		})
	}
}

func TestSyntheticInstallationInstalledReadOnly(t *testing.T) {
	cli := os.Getenv("SIQ_HERMES_NATIVE_CLI")
	if cli == "" {
		t.Skip("explicit installed layout check")
	}
	pins, err := inspectSyntheticInstallation(cli)
	if err != nil {
		t.Fatal(err)
	}
	absent := 0
	for _, pin := range pins {
		if pin.info == nil && strings.HasSuffix(pin.path, ".env") {
			absent++
		}
	}
	if absent != 2 {
		t.Fatal("installed fallback environment not pinned")
	}
}

func TestSyntheticOverlayPinnedForInvocation(t *testing.T) {
	target, materials, _ := scopeTestFixture(t)
	s, err := prepareSyntheticModelScopeWithParser(target, materials, scopeTestURL, scopeTestID, scopeTestJSON)
	if err != nil {
		t.Fatal(err)
	}
	pin, err := s.pin()
	if err != nil {
		t.Fatal(err)
	}
	defer pin.Close()
	path := filepath.Join(s.dir, "config.yaml")
	if os.WriteFile(path, []byte("broken"), 0600) == nil {
		t.Fatal("pinned overlay overwritten")
	}
	if os.Remove(path) == nil {
		t.Fatal("pinned overlay removed")
	}
	if os.Rename(s.dir, s.dir+".moved") == nil {
		t.Fatal("pinned overlay parent moved")
	}
	// Holding this read scope does not prevent unrelated receipt publication.
	other, err := statefs.CreatePrivate(filepath.Join(materials, "sibling-receipt"))
	if err != nil {
		t.Fatal("pin blocked unrelated publication", err)
	}
	if err := other.Close(); err != nil {
		t.Fatal(err)
	}
	if err := s.verify(); err != nil {
		t.Fatal(err)
	}
	if err := pin.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal("overlay remained locked", err)
	}
}

func TestSyntheticModelInstalledOfflineConfig(t *testing.T) {
	cli := os.Getenv("SIQ_HERMES_NATIVE_CLI")
	if cli == "" {
		t.Skip("explicit offline native configuration parsing")
	}
	target, materials, _ := scopeTestFixture(t)
	target.NativeCLI = cli
	s, err := prepareSyntheticModelScope(target, materials, scopeTestURL, scopeTestID)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.verify(); err != nil {
		t.Fatal(err)
	}
}
