// Package evidencetest provides real isolated state for evidence component tests.
// It must only be imported by test files; its synthetic references are not Grants.
package evidencetest

import (
	"runtime"
	"testing"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

type Fixture struct {
	Dir     string
	Key     *signing.Key
	Store   *effectevidence.Store
	Profile runtimeaction.FilesystemProfile
}

func New(t *testing.T) Fixture {
	t.Helper()
	st, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	_, initErr := st.Initialize(w, 47611)
	releaseErr := w.Release()
	if initErr != nil || releaseErr != nil {
		t.Fatal(initErr, releaseErr)
	}
	key, err := signing.Load(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	profile := runtimeaction.FilesystemPOSIXV1
	if runtime.GOOS == "windows" {
		if _, err := st.ActivateWindowsProfile(true, "evidence-component-test"); err != nil {
			t.Fatal(err)
		}
		profile = runtimeaction.FilesystemWindowsLocalDriveV1
	}
	store, err := effectevidence.NewStore(st.Dir, key)
	if err != nil {
		t.Fatal(err)
	}
	return Fixture{st.Dir, key, store, profile}
}

func (f Fixture) Capture(path string, max int64) (effectevidence.FileSnapshot, error) {
	return effectevidence.CaptureFileForProfile(f.Profile, path, max)
}

func (f Fixture) Pending(p effectevidence.PendingFile) effectevidence.PendingFile {
	if f.Profile == runtimeaction.FilesystemWindowsLocalDriveV1 {
		p.SchemaVersion = "file-observation-pending/v2"
		p.IntentID = "int-component"
		p.IntentDigest = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
	}
	return p
}

func (f Fixture) Resources(t *testing.T, path string) []runtimeaction.ResourceRef {
	t.Helper()
	canonical, err := runtimeaction.NormalizeResourceForProfile(f.Profile, "filesystem", path)
	if err != nil {
		t.Fatal(err)
	}
	return runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "filesystem", Value: canonical}})
}
