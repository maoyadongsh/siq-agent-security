package stateformat

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/privatefs"
)

const WindowsProfileDir = "state-windows-profile-v1"
const WindowsProfilePlanSchema = "state-windows-profile-plan/v1"
const WindowsProfileBudget = 16 << 10
const WindowsResourceProfile = "windows-local-drive/v1"

var ErrWindowsProfileMigration = errors.New("state: Windows resource profile activation incomplete or invalid")

// WindowsProfilePlan preserves original marker bytes and migration lineage.
// It is compatibility metadata, never an authorization or a business backup.
type WindowsProfilePlan struct {
	Schema        string `json:"schema"`
	Profile       string `json:"filesystem_profile"`
	SourceMarker  string `json:"source_marker"`
	TargetMarker  string `json:"target_marker"`
	MigrationHash string `json:"migration_history_sha256"`
}

type WindowsProfileDone struct {
	Schema string `json:"schema"`
	Plan   string `json:"plan_sha256"`
	Marker string `json:"marker_sha256"`
}

func EncodeWindowsProfilePlan(p WindowsProfilePlan) []byte {
	b, _ := json.Marshal(p)
	return append(b, '\n')
}

// Profile metadata is deliberately independent of statefs: that wrapper must
// reject the active transition. Windows still requires private, ordinary,
// single-link objects; retaining ReadRegular also preserves identity rechecks.
func readWindowsProfileMetadata(path string, limit int64) ([]byte, error) {
	raw, err := ReadRegular(path, limit)
	if err != nil || runtime.GOOS != "windows" {
		return raw, err
	}
	if err := privatefs.CheckDir(filepath.Dir(path)); err != nil {
		return nil, ErrCorrupt
	}
	private, err := privatefs.ReadFile(path, limit)
	if err != nil || !bytes.Equal(private, raw) {
		return nil, ErrCorrupt
	}
	return raw, nil
}

func DecodeWindowsProfilePlan(raw []byte) (WindowsProfilePlan, error) {
	var p WindowsProfilePlan
	if len(raw) > WindowsProfileBudget || DecodeObject(raw, []string{"schema", "filesystem_profile", "source_marker", "target_marker", "migration_history_sha256"}, &p) != nil || p.Schema != WindowsProfilePlanSchema || p.Profile != WindowsResourceProfile || (p.MigrationHash != "absent" && !Digest(p.MigrationHash)) || !bytes.Equal(raw, EncodeWindowsProfilePlan(p)) {
		return p, ErrCorrupt
	}
	source, se := Decode([]byte(p.SourceMarker))
	target, te := Decode([]byte(p.TargetMarker))
	if se != nil || te != nil || source.Schema != "state-format/v2" || source.MinReader != 2 || source.MinWriter != 2 || target.Schema != "state-format/v2" || target.MinReader != 3 || target.MinWriter != 3 || source.DirectoryID != target.DirectoryID || source.InstanceID != target.InstanceID {
		return p, ErrCorrupt
	}
	return p, nil
}

// WindowsProfileHistory validates the completed original migration, if any.
// It does not modify or revalidate all business backup files.
func WindowsProfileHistory(dir string, source []byte) (string, error) {
	plan, pe := readWindowsProfileMetadata(filepath.Join(dir, MigrationDir, "plan.json"), 8<<20)
	done, de := readWindowsProfileMetadata(filepath.Join(dir, MigrationDir, "done.json"), Budget)
	if errors.Is(pe, os.ErrNotExist) && errors.Is(de, os.ErrNotExist) {
		return "absent", nil
	}
	if pe != nil || de != nil {
		return "", ErrCorrupt
	}
	var prior struct {
		Schema    string          `json:"schema"`
		Directory string          `json:"state_directory_id"`
		Instance  string          `json:"instance_id"`
		Source    string          `json:"source_marker_sha256"`
		Target    json.RawMessage `json:"target"`
		Entries   json.RawMessage `json:"entries"`
	}
	var finished WindowsProfileDone
	if DecodeObject(plan, []string{"schema", "state_directory_id", "instance_id", "source_marker_sha256", "target", "entries"}, &prior) != nil || prior.Schema != "state-migration-plan/v1" || DecodeObject(done, []string{"schema", "plan_sha256", "marker_sha256"}, &finished) != nil || finished.Schema != "state-migration-done/v1" || finished.Plan != Hash(plan) || finished.Marker != Hash(source) {
		return "", ErrCorrupt
	}
	original, oe := Decode(source)
	target, te := Decode(prior.Target)
	if oe != nil || te != nil || original != target || prior.Directory != original.DirectoryID || prior.Instance != original.InstanceID {
		return "", ErrCorrupt
	}
	return Hash([]byte("state-windows-profile-history/v1\x00" + Hash(plan) + "\x00" + Hash(done))), nil
}

func ValidateWindowsProfilePlan(dir string, p WindowsProfilePlan) error {
	if _, err := DecodeWindowsProfilePlan(EncodeWindowsProfilePlan(p)); err != nil {
		return err
	}
	m, _ := Decode([]byte(p.TargetMarker))
	if err := ValidateBinding(dir, m); err != nil {
		return err
	}
	history, err := WindowsProfileHistory(dir, []byte(p.SourceMarker))
	if err != nil || history != p.MigrationHash {
		return ErrCorrupt
	}
	return nil
}

func CheckWindowsProfileCompleted(dir string, raw []byte) error {
	p, err := DecodeWindowsProfilePlan(raw)
	if err != nil || ValidateWindowsProfilePlan(dir, p) != nil {
		return ErrCorrupt
	}
	if err := privatefs.CheckDir(dir); err != nil {
		return ErrCorrupt
	}
	archive, err := readWindowsProfileMetadata(filepath.Join(dir, WindowsProfileDir, "plan.json"), WindowsProfileBudget)
	if err != nil || !bytes.Equal(archive, raw) {
		return ErrMigration
	}
	prepared, err := readWindowsProfileMetadata(filepath.Join(dir, WindowsProfileDir, "prepared.json"), Budget)
	var proof struct {
		Plan string `json:"plan_sha256"`
	}
	if err != nil || DecodeObject(prepared, []string{"plan_sha256"}, &proof) != nil || proof.Plan != Hash(raw) {
		return ErrMigration
	}
	done, err := readWindowsProfileMetadata(filepath.Join(dir, WindowsProfileDir, "done.json"), Budget)
	if err != nil {
		return ErrMigration
	}
	var d WindowsProfileDone
	if DecodeObject(done, []string{"schema", "plan_sha256", "marker_sha256"}, &d) != nil || d.Schema != "state-windows-profile-done/v1" || d.Plan != Hash(raw) || d.Marker != Hash([]byte(p.TargetMarker)) {
		return ErrCorrupt
	}
	live, err := readWindowsProfileMetadata(filepath.Join(dir, MarkerName), Budget)
	if err != nil || string(live) != p.TargetMarker {
		return ErrCorrupt
	}
	return nil
}

func checkWindowsProfile(dir string, m Marker) error {
	raw, err := readWindowsProfileMetadata(filepath.Join(dir, WindowsProfileDir, "plan.json"), WindowsProfileBudget)
	if errors.Is(err, os.ErrNotExist) && m.MinReader < 3 {
		return nil
	}
	if err != nil {
		return errors.Join(ErrMigration, ErrWindowsProfileMigration)
	}
	if err := CheckWindowsProfileCompleted(dir, raw); err != nil {
		return errors.Join(err, ErrWindowsProfileMigration)
	}
	return nil
}

func RequireWindowsProfile(dir string) error {
	if err := RequirePath(dir, true); err != nil {
		return err
	}
	m, err := ReadMarker(dir)
	if err != nil || m.Schema != "state-format/v2" || m.MinReader != 3 || m.MinWriter != 3 {
		return Fail(ErrMigration)
	}
	return nil
}
