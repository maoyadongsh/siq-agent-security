package state

import (
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func TestWindowsStatePathEnvironment(t *testing.T) {
	parent := t.TempDir()
	valid := filepath.Join(parent, "中文 状态")
	fallback := filepath.Join(parent, "fallback")
	t.Setenv(product.EnvStateDirOld, fallback)
	t.Setenv("LOCALAPPDATA", parent)
	before := treeSnapshot(t, parent)
	for _, raw := range []string{valid + ".", valid + " ", " ", "   ", parent + `\bad.\..\target`, parent + `/bad /../target`} {
		t.Setenv(product.EnvStateDir, raw)
		if got, err := DefaultDir(); got != "" || !errors.Is(err, ErrCorruptState) {
			t.Error("invalid primary must fail without fallback")
		}
	}
	t.Setenv(product.EnvStateDir, "")
	if got, err := DefaultDir(); err != nil || got != fallback {
		t.Fatal("empty primary did not select valid legacy value")
	}
	t.Setenv(product.EnvStateDirOld, fallback+" ")
	if got, err := DefaultDir(); got != "" || !errors.Is(err, ErrCorruptState) {
		t.Error("invalid legacy must fail without default fallback")
	}
	t.Setenv(product.EnvStateDir, valid)
	if got, err := DefaultDir(); err != nil || got != valid {
		t.Error("valid primary spelling or priority changed")
	}
	t.Setenv(product.EnvStateDir, "")
	t.Setenv(product.EnvStateDirOld, "")
	for _, raw := range []string{parent + ".", parent + `\bad.\..`, parent + `/bad /..`} {
		t.Setenv("LOCALAPPDATA", raw)
		if got, err := DefaultDir(); got != "" || !errors.Is(err, ErrCorruptState) {
			t.Error("invalid default base accepted")
		}
	}
	t.Setenv("LOCALAPPDATA", "")
	t.Setenv("USERPROFILE", parent+`\bad.\..`)
	if got, err := DefaultDir(); got != "" || !errors.Is(err, ErrCorruptState) {
		t.Error("invalid home fallback accepted")
	}
	if !reflect.DeepEqual(before, treeSnapshot(t, parent)) {
		t.Error("path selection changed fixture contents")
	}
}

func TestWindowsStatePathDirectAPIsRejectBeforeEffects(t *testing.T) {
	for _, initialized := range []bool{false, true} {
		name := "empty"
		if initialized {
			name = "initialized"
		}
		t.Run(name, func(t *testing.T) {
			parent := t.TempDir()
			target := filepath.Join(parent, "target")
			if err := os.Mkdir(target, 0700); err != nil {
				t.Fatal(err)
			}
			if initialized {
				st, err := Open(target)
				if err != nil {
					t.Fatal(err)
				}
				w, err := AcquireWriter(target)
				if err != nil {
					t.Fatal(err)
				}
				t.Cleanup(func() { _ = w.Release() })
				if _, err := st.Initialize(w, 0); err != nil {
					t.Fatal(err)
				}
				if err := w.Release(); err != nil {
					t.Fatal(err)
				}
				if _, err := st.Token(); err != nil {
					t.Fatal(err)
				}
				if _, err := st.RecoveryToken(); err != nil {
					t.Fatal(err)
				}
			}
			before := treeSnapshot(t, parent)
			// Deliberately concatenate raw components: Join would erase the attack.
			paths := []string{target + ".", target + " ", target + `.\`, target + " /", parent + `\bad.\..\target`, parent + `/bad /../target`, target + `.\child`, target + ` \child`}
			for i, raw := range paths {
				st := &Store{Dir: raw}
				operations := []struct {
					name string
					run  func() error
				}{
					{"open", func() error { _, e := Open(raw); return e }},
					{"compatibility", func() error { _, e := CheckStateCompatibility(raw); return e }},
					{"require", func() error { return RequireStateCompatibility(raw) }},
					{"writer", func() error {
						w, e := AcquireWriter(raw)
						if w != nil {
							t.Cleanup(func() { _ = w.Release() })
							_ = w.Release()
						}
						return e
					}},
					{"scoped-writer", func() error {
						w, e := AcquireScopedWriter(raw, "service-control")
						if w != nil {
							t.Cleanup(func() { _ = w.Release() })
							_ = w.Release()
						}
						return e
					}},
					{"writer-held", func() error { _, _, e := WriterHeld(raw); return e }},
					{"directory-id", func() error { _, e := st.DirectoryID(); return e }},
					{"load-config", func() error { _, e := st.LoadConfig(); return e }},
					{"save-config", func() error { return st.SaveConfig(Config{EnforcementMode: "block", Port: 47611}) }},
					{"token", func() error { _, e := st.Token(); return e }},
					{"recovery-read", func() error { _, e := st.ReadRecoveryToken(); return e }},
					{"recovery-create", func() error { _, e := st.RecoveryToken(); return e }},
					{"instance", func() error { _, e := st.ReadLocalInstance(); return e }},
					{"initialize", func() error { _, e := st.Initialize(nil, 0); return e }},
					{"enforce", func() error { return st.EnforceStateCompatibility(nil, "") }},
					{"migrate", func() error { _, e := st.MigrateState("test"); return e }},
					{"format-parents", func() error { return stateformat.CheckParents(raw) }},
					{"format-id", func() error { _, e := stateformat.DirectoryID(raw); return e }},
					{"format-marker", func() error { _, e := stateformat.ReadMarker(raw); return e }},
					{"format-regular", func() error {
						b, e := stateformat.ReadRegular(raw+`\config.json`, 65536)
						if len(b) != 0 {
							t.Error("regular read returned alias content")
						}
						return e
					}},
					{"bad-writer-initialize", func() error { _, e := (&Store{Dir: target}).Initialize(&Writer{Dir: raw}, 0); return e }},
					{"bad-writer-enforce", func() error { return (&Store{Dir: target}).EnforceStateCompatibility(&Writer{Dir: raw}, "") }},
					{"checked-compat-root", func() error {
						w, e := acquireWriterChecked(target, raw, func() error { return nil })
						if w != nil {
							_ = w.Release()
						}
						return e
					}},
					{"format-path-read", func() error { return stateformat.RequirePath(raw, false) }},
					{"format-path-write", func() error { return stateformat.RequirePath(raw, true) }},
				}
				for _, op := range operations {
					if err := op.run(); !errors.Is(err, ErrCorruptState) {
						t.Errorf("vector %d %s: expected path rejection", i, op.name)
					} else if strings.Contains(err.Error(), parent) {
						t.Errorf("vector %d %s: error leaked path", i, op.name)
					}
					if !reflect.DeepEqual(before, treeSnapshot(t, parent)) {
						t.Fatalf("vector %d %s changed fixture", i, op.name)
					}
				}
			}
		})
	}
}

func TestWindowsStatePathValidNavigationAndInitialization(t *testing.T) {
	parent := t.TempDir()
	raw := parent + `\中文 状态\..\normal name`
	st, err := Open(raw)
	if err != nil {
		t.Fatal(err)
	}
	w, err := AcquireWriter(raw)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = w.Release() })
	if _, err := st.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	if _, err := st.LoadConfig(); err != nil {
		t.Fatal(err)
	}
	if _, err := st.ReadLocalInstance(); err != nil {
		t.Fatal(err)
	}
	if _, err := st.DirectoryID(); err != nil {
		t.Fatal(err)
	}
	if _, err := st.Token(); err != nil {
		t.Fatal(err)
	}
	if _, err := st.RecoveryToken(); err != nil {
		t.Fatal(err)
	}
	if err := w.Release(); err != nil {
		t.Fatal(err)
	}
	if _, err := st.MigrateState("test"); err != nil {
		t.Fatal(err)
	}
	scoped, err := AcquireScopedWriter(raw, "service-control")
	if err != nil {
		t.Fatal(err)
	}
	if err := scoped.Release(); err != nil {
		t.Fatal(err)
	}
}

func TestWindowsStatePathOwnedWriterRejectsRawAliases(t *testing.T) {
	parent := t.TempDir()
	target := filepath.Join(parent, "target")
	st, err := Open(target)
	if err != nil {
		t.Fatal(err)
	}
	w, err := AcquireWriter(target)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { w.Dir = target; _ = w.Release() })
	if _, err := st.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	key, err := signing.FromSeed(make([]byte, 32))
	if err != nil {
		t.Fatal(err)
	}
	unit := []byte("[Service]\nExecStart=/synthetic serve\n")
	before := treeSnapshot(t, parent)
	// The lock path, PID and nonce are real and stay unchanged. Only the
	// exported directory spelling is replaced; this is not a forged owner.
	for _, changeWriter := range []bool{false, true} {
		func() {
			defer func() { st.Dir = target; w.Dir = target }()
			raw := parent + `\bad.\..\target`
			if changeWriter {
				w.Dir = raw
			} else {
				st.Dir = raw
			}
			ops := []struct {
				name string
				run  func() error
			}{
				{"enforce", func() error { return st.EnforceStateCompatibility(w, "") }},
				{"initialize", func() error { _, e := st.Initialize(w, 0); return e }},
				{"grant-recovery", func() error { _, e := st.RecoverGrantCommits(w); return e }},
				{"service-switch", func() error { _, e := st.PrepareServiceSwitch(w, key, unit, []byte("changed")); return e }},
				{"user-service", func() error { _, e := st.PrepareUserService(w, key, unit); return e }},
			}
			for _, op := range ops {
				if err := op.run(); !errors.Is(err, ErrCorruptState) {
					t.Errorf("%s accepted an aliased owner directory", op.name)
				}
				if !reflect.DeepEqual(before, treeSnapshot(t, parent)) {
					t.Fatalf("%s changed state on invalid owner spelling", op.name)
				}
			}
		}()
	}
	if n, err := st.RecoverGrantCommits(w); err != nil || n != 0 {
		t.Fatal("valid grant recovery changed")
	}
	if err := st.serviceWriter(w); err != nil {
		t.Fatal("valid service writer rejected")
	}
	// This only prepares files inside the fixture; no service manager is run.
	if _, err := st.PrepareUserService(w, key, unit); err != nil {
		t.Fatal(err)
	}
	if err := w.Release(); err != nil {
		t.Fatal(err)
	}
}
