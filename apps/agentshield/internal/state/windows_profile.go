package state

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"time"

	"siq-agent-security/apps/agentshield/internal/privatefs"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

var ErrWindowsProfileActivation = errors.New("state: Windows profile activation requires confirmed compatible state")

// ActivateWindowsProfile changes compatibility metadata only. It never issues,
// upgrades or approves a Grant. The complete new authority chain is a separate
// prerequisite for exposing new Grant creation in management entry points.
func (s *Store) ActivateWindowsProfile(confirm bool, version string) (string, error) {
	return s.activateWindowsProfile(confirm, version, nil)
}

// fault is a test-only seam; there is no runtime fault configuration.
func (s *Store) activateWindowsProfile(confirm bool, version string, fault func(string) error) (status string, resultErr error) {
	if !confirm || runtime.GOOS != "windows" || !filepath.IsAbs(s.Dir) || stateformat.ValidatePath(s.Dir) != nil || privatefs.CheckDir(s.Dir) != nil || stateformat.RequirePath(filepath.Dir(s.Dir), true) != nil {
		return "", ErrWindowsProfileActivation
	}
	active := filepath.Join(s.Dir, stateformat.PlanName)
	journal := filepath.Join(s.Dir, stateformat.WindowsProfileDir)
	readPlan := func() ([]byte, stateformat.WindowsProfilePlan, error) {
		raw, err := migrationReadRegular(active, stateformat.WindowsProfileBudget)
		if err != nil {
			return nil, stateformat.WindowsProfilePlan{}, err
		}
		p, err := stateformat.DecodeWindowsProfilePlan(raw)
		if err == nil {
			err = stateformat.ValidateWindowsProfilePlan(s.Dir, p)
		}
		if err == nil {
			err = validateWindowsProfileLive(s.Dir, raw, p)
		}
		return raw, p, err
	}
	check := func() error {
		_, _, err := readPlan()
		if errors.Is(err, os.ErrNotExist) {
			if err := stateformat.Check(s.Dir, true, false); err != nil {
				return err
			}
			m, err := stateformat.ReadMarker(s.Dir)
			if err != nil || m.Schema != "state-format/v2" || m.MinReader != m.MinWriter || (m.MinReader != 2 && m.MinReader != 3) {
				return ErrWindowsProfileActivation
			}
			if m.MinReader == 2 {
				original, err := migrationReadRegular(filepath.Join(s.Dir, stateformat.MarkerName), stateformat.Budget)
				if err != nil {
					return err
				}
				if _, err := stateformat.WindowsProfileHistory(s.Dir, original); err != nil {
					return err
				}
				m.ProgramVersion = version
				if _, err := stateformat.Decode(migrationJSON(m)); err != nil {
					return err
				}
				if entries, err := os.ReadDir(journal); err == nil {
					if err := privatefs.CheckDir(journal); err != nil {
						return err
					}
					for _, entry := range entries {
						if entry.Name() != "tmp" || !entry.IsDir() {
							return ErrWindowsProfileActivation
						}
					}
				} else if !errors.Is(err, os.ErrNotExist) {
					return err
				}
			}
			return nil
		}
		return err
	}
	if err := check(); err != nil {
		return "", err
	}
	var locks []*Writer
	defer func() {
		for i := len(locks) - 1; i >= 0; i-- {
			resultErr = errors.Join(resultErr, locks[i].Release())
		}
	}()
	for _, scope := range []string{"", "service-control", "adapter-write", "client-releases", "client-snapshots"} {
		w, err := acquireWriterChecked(filepath.Join(s.Dir, scope), s.Dir, check)
		if err != nil {
			return "", err
		}
		locks = append(locks, w)
	}
	publish := func(path string, raw []byte) error {
		return migrationPublishInJournal(s.Dir, path, filepath.Join(journal, "tmp"), raw, 0600)
	}
	fail := func(at string) error {
		if fault != nil {
			return fault(at)
		}
		return nil
	}
	raw, plan, err := readPlan()
	if errors.Is(err, os.ErrNotExist) {
		original, e := migrationReadRegular(filepath.Join(s.Dir, stateformat.MarkerName), stateformat.Budget)
		if e != nil {
			return "", e
		}
		source, e := stateformat.Decode(original)
		if e != nil || source.Schema != "state-format/v2" {
			return "", ErrWindowsProfileActivation
		}
		if source.MinReader == 3 && source.MinWriter == 3 {
			if e := stateformat.RequireWindowsProfile(s.Dir); e != nil {
				return "", e
			}
			return "up_to_date", nil
		}
		if source.MinReader != 2 || source.MinWriter != 2 {
			return "", ErrWindowsProfileActivation
		}
		target := source
		target.MinReader, target.MinWriter = 3, 3
		target.ProgramVersion = version
		target.PublishedAt = time.Now().UTC().Format(time.RFC3339Nano)
		history, e := stateformat.WindowsProfileHistory(s.Dir, original)
		if e != nil {
			return "", e
		}
		plan = stateformat.WindowsProfilePlan{Schema: stateformat.WindowsProfilePlanSchema, Profile: stateformat.WindowsResourceProfile, SourceMarker: string(original), TargetMarker: string(migrationJSON(target)), MigrationHash: history}
		if e := stateformat.ValidateWindowsProfilePlan(s.Dir, plan); e != nil {
			return "", e
		}
		if list, e := os.ReadDir(journal); e == nil {
			for _, entry := range list {
				if entry.Name() != "tmp" || !entry.IsDir() {
					return "", ErrWindowsProfileActivation
				}
			}
		} else if !errors.Is(e, os.ErrNotExist) {
			return "", e
		}
		if e := migrationPrivateDir(journal); e != nil {
			return "", e
		}
		raw = stateformat.EncodeWindowsProfilePlan(plan)
		if e := publish(active, raw); e != nil {
			return "", e
		}
	} else if err != nil {
		return "", err
	}
	if err := fail("plan"); err != nil {
		return "", err
	}
	if err := stateformat.ValidateWindowsProfilePlan(s.Dir, plan); err != nil {
		return "", err
	}
	if err := validateWindowsProfileLive(s.Dir, raw, plan); err != nil {
		return "", err
	}
	if err := publish(filepath.Join(journal, "plan.json"), raw); err != nil {
		return "", err
	}
	if err := fail("archived"); err != nil {
		return "", err
	}
	live := filepath.Join(s.Dir, stateformat.MarkerName)
	current, err := migrationReadRegular(live, stateformat.Budget)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return "", err
	}
	if string(current) != plan.TargetMarker {
		staged := filepath.Join(journal, "target.json")
		if err := publish(staged, []byte(plan.TargetMarker)); err != nil {
			return "", err
		}
		if err := publish(filepath.Join(journal, "prepared.json"), migrationJSON(map[string]string{"plan_sha256": stateformat.Hash(raw)})); err != nil {
			return "", err
		}
		if err := fail("prepared"); err != nil {
			return "", err
		}
		if err := validateWindowsProfileLive(s.Dir, raw, plan); err != nil {
			return "", err
		}
		if err := os.Rename(staged, live); err != nil {
			return "", err
		}
		if err := migrationSync(s.Dir); err != nil {
			return "", err
		}
	}
	if err := fail("marker"); err != nil {
		return "", err
	}
	if err := stateformat.ValidateWindowsProfilePlan(s.Dir, plan); err != nil {
		return "", err
	}
	current, err = migrationReadRegular(live, stateformat.Budget)
	if err != nil || string(current) != plan.TargetMarker {
		return "", ErrWindowsProfileActivation
	}
	done := stateformat.WindowsProfileDone{Schema: "state-windows-profile-done/v1", Plan: stateformat.Hash(raw), Marker: stateformat.Hash(current)}
	if err := publish(filepath.Join(journal, "done.json"), migrationJSON(done)); err != nil {
		return "", err
	}
	if err := fail("done"); err != nil {
		return "", err
	}
	if err := stateformat.CheckWindowsProfileCompleted(s.Dir, raw); err != nil {
		return "", err
	}
	current, err = migrationReadRegular(active, stateformat.WindowsProfileBudget)
	if err != nil || !bytes.Equal(current, raw) {
		return "", ErrWindowsProfileActivation
	}
	if err := os.Remove(active); err != nil {
		return "", err
	}
	if err := migrationSync(filepath.Dir(active)); err != nil {
		return "", err
	}
	return "activated", nil
}

func validateWindowsProfileLive(dir string, raw []byte, p stateformat.WindowsProfilePlan) error {
	current, err := migrationReadRegular(filepath.Join(dir, stateformat.MarkerName), stateformat.Budget)
	if err == nil {
		if string(current) == p.SourceMarker {
			return nil
		}
		if string(current) != p.TargetMarker {
			return ErrWindowsProfileActivation
		}
	}
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	journal := filepath.Join(dir, stateformat.WindowsProfileDir)
	archived, ae := migrationReadRegular(filepath.Join(journal, "plan.json"), stateformat.WindowsProfileBudget)
	prepared, pe := migrationReadRegular(filepath.Join(journal, "prepared.json"), stateformat.Budget)
	var proof struct {
		Plan string `json:"plan_sha256"`
	}
	if ae != nil || pe != nil || !bytes.Equal(archived, raw) || stateformat.DecodeObject(prepared, []string{"plan_sha256"}, &proof) != nil || proof.Plan != stateformat.Hash(raw) {
		return ErrWindowsProfileActivation
	}
	// Once the target is live, its archived preparation must already exist.
	// Reconstructing either record would hide loss of immutable history.
	if err == nil {
		return nil
	}
	target, te := migrationReadRegular(filepath.Join(journal, "target.json"), stateformat.Budget)
	if te != nil || string(target) != p.TargetMarker {
		return ErrWindowsProfileActivation
	}
	return nil
}
