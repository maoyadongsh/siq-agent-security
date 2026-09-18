package state

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"sort"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/privatefs"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

const migrationMaxEntries = 10000
const migrationMaxFile int64 = 128 << 20
const migrationMaxBytes int64 = 2 << 30

// Set only by isolated process tests, never by runtime configuration.
var migrationPublicationTestHook func(string)

type MigrationEntry struct {
	Path      string `json:"path"`
	Mode      uint32 `json:"mode"`
	Directory bool   `json:"directory"`
	Size      int64  `json:"size"`
	SHA256    string `json:"sha256"`
}
type MigrationPlan struct {
	Schema       string             `json:"schema"`
	DirectoryID  string             `json:"state_directory_id"`
	InstanceID   string             `json:"instance_id"`
	SourceMarker string             `json:"source_marker_sha256"`
	Target       stateformat.Marker `json:"target"`
	Entries      []MigrationEntry   `json:"entries"`
}
type MigrationResult struct {
	Schema string `json:"schema"`
	Status string `json:"status"`
	Format int    `json:"format_version"`
	Files  int    `json:"backup_entries"`
}

func (s *Store) newFormatMarker(version string) (stateformat.Marker, error) {
	instance, e := s.ReadLocalInstance()
	if e != nil {
		return stateformat.Marker{}, e
	}
	dir, e := s.DirectoryID()
	if e != nil {
		return stateformat.Marker{}, e
	}
	return stateformat.Marker{Schema: "state-format/v2", ProgramVersion: version, FormatVersion: 2, PublishedAt: time.Now().UTC().Format(time.RFC3339Nano), MinReader: 2, MinWriter: 2, DirectoryID: dir, InstanceID: instance.InstanceID}, nil
}
func migrationExcluded(rel string) bool {
	if rel == stateformat.MigrationDir || strings.HasPrefix(rel, stateformat.MigrationDir+"/") || rel == stateformat.PlanName {
		return true
	}
	// Runtime lock bytes are process ownership, never restorable authority.
	for _, scope := range []string{"", "service-control/", "adapter-write/", "client-releases/", "client-snapshots/"} {
		if rel == scope+LockFile || strings.HasPrefix(rel, scope+LockFile+".stale.") {
			return true
		}
	}
	return false
}
func snapshotMigration(dir string) ([]MigrationEntry, error) { return snapshotMigrationTree(dir, true) }
func snapshotMigrationTree(dir string, exclude bool) ([]MigrationEntry, error) {
	if err := privatefs.CheckDir(dir); err != nil {
		return nil, err
	}
	entries := []MigrationEntry{}
	var total int64
	err := filepath.WalkDir(dir, func(p string, d os.DirEntry, e error) error {
		if e != nil {
			return errors.New("state-migrate: cannot inventory state")
		}
		rel, e := filepath.Rel(dir, p)
		if e != nil {
			return e
		}
		rel = filepath.ToSlash(rel)
		if rel == "." {
			return nil
		}
		if exclude && migrationExcluded(rel) {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if len(entries) >= migrationMaxEntries {
			return errors.New("state-migrate: entry budget exceeded")
		}
		info, e := os.Lstat(p)
		if e != nil || (!info.IsDir() && !info.Mode().IsRegular()) || info.Mode()&(os.ModeSetuid|os.ModeSetgid|os.ModeSticky) != 0 {
			return errors.New("state-migrate: nonregular entry rejected")
		}
		if info.IsDir() {
			if err := privatefs.CheckDir(p); err != nil {
				return err
			}
		}
		row := MigrationEntry{Path: rel, Mode: uint32(info.Mode().Perm()), Directory: info.IsDir()}
		if !row.Directory {
			if info.Size() > migrationMaxFile || total+info.Size() > migrationMaxBytes {
				return errors.New("state-migrate: backup byte budget exceeded")
			}
			b, e := privatefs.ReadFile(p, migrationMaxFile)
			if e != nil {
				return errors.New("state-migrate: source changed")
			}
			row.Size = int64(len(b))
			row.SHA256 = stateformat.Hash(b)
			total += row.Size
		}
		entries = append(entries, row)
		return nil
	})
	sort.Slice(entries, func(i, j int) bool { return entries[i].Path < entries[j].Path })
	return entries, err
}
func migrationSync(dir string) error {
	if runtime.GOOS == "windows" {
		return nil
	}
	f, e := os.Open(dir)
	if e != nil {
		return e
	}
	defer f.Close()
	return f.Sync()
}

// Migration owns the active compatibility barrier, so its private reads cannot
// use the ordinary statefs wrapper. Keep the pre-existing POSIX reader intact.
func migrationReadRegular(path string, limit int64) ([]byte, error) {
	if runtime.GOOS != "windows" {
		return stateformat.ReadRegular(path, limit)
	}
	if err := stateformat.ValidatePath(path); err != nil {
		return nil, err
	}
	if err := privatefs.CheckDir(filepath.Dir(path)); err != nil {
		return nil, err
	}
	return privatefs.ReadFile(path, limit)
}

// Migration-only raw publication. Callers hold every writer and validate the
// immutable plan. Ordinary statefs intentionally refuses this active barrier.
func migrationPublish(root, path string, b []byte, mode os.FileMode) (resultErr error) {
	return migrationPublishInJournal(root, path, filepath.Join(root, stateformat.MigrationDir, "tmp"), b, mode)
}

func migrationPublishInJournal(root, path, scratch string, b []byte, mode os.FileMode) (resultErr error) {
	if err := privatefs.CheckDir(root); err != nil {
		return err
	}
	if err := privatefs.CheckDir(filepath.Dir(path)); err != nil {
		return err
	}
	if e := stateformat.CheckParents(filepath.Dir(path)); e != nil {
		return e
	}
	if old, e := privatefs.ReadFile(path, migrationMaxFile); e == nil {
		info, se := os.Lstat(path)
		if se != nil || string(old) != string(b) || !migrationModeMatches(info.Mode(), mode) {
			return errors.New("state-migrate: existing output differs")
		}
		return nil
	} else if !errors.Is(e, os.ErrNotExist) {
		return errors.New("state-migrate: unsafe output")
	}
	if e := migrationPrivateDir(scratch); e != nil {
		return e
	}
	f, e := privatefs.CreateTemp(scratch, ".migration-*")
	if e != nil {
		return e
	}
	created, e := f.Stat()
	if e != nil {
		_ = f.Close()
		return e
	}
	moved := false
	defer func() {
		if !moved {
			resultErr = errors.Join(resultErr, migrationRemoveScratch(f.Name(), created))
		}
	}()
	if e = f.Chmod(mode); e == nil {
		_, e = f.Write(b)
	}
	if e == nil {
		e = f.Sync()
	}
	e = errors.Join(e, f.Close())
	if e != nil {
		return e
	}
	if migrationPublicationTestHook != nil {
		migrationPublicationTestHook("before-publish")
	}
	if moved, e = migrationPublishScratch(f.Name(), path, created); e != nil {
		return e
	}
	if migrationPublicationTestHook != nil {
		migrationPublicationTestHook("published")
	}
	return migrationSync(filepath.Dir(path))
}

// Windows Chmod only controls FILE_ATTRIBUTE_READONLY through owner-write.
// This is a mode-equivalence check, not a claim about Windows DACL privacy.
func migrationModeMatches(actual, requested os.FileMode) bool {
	if runtime.GOOS == "windows" {
		return actual&0200 == requested&0200
	}
	return actual.Perm() == requested.Perm()
}

func migrationMkdir(path string, mode os.FileMode) error {
	if runtime.GOOS == "windows" {
		if err := privatefs.MkdirAll(path); err != nil {
			return err
		}
		return migrationSync(filepath.Dir(path))
	}
	if e := os.Mkdir(path, mode); e != nil && !errors.Is(e, os.ErrExist) {
		return e
	}
	i, e := os.Lstat(path)
	if e != nil || !i.IsDir() {
		return errors.New("state-migrate: unsafe backup directory")
	}
	return migrationSync(filepath.Dir(path))
}
func migrationPrivateDir(path string) error {
	if e := migrationMkdir(path, 0700); e != nil {
		return e
	}
	i, e := os.Lstat(path)
	if e != nil || !i.IsDir() || (runtime.GOOS != "windows" && i.Mode().Perm()&0077 != 0) {
		return errors.New("state-migrate: private journal required")
	}
	return nil
}
func migrationJSON(v any) []byte { b, _ := json.Marshal(v); return append(b, '\n') }
func migrationCheckpoint(dir, name, hash string) error {
	return migrationPublish(dir, filepath.Join(dir, stateformat.MigrationDir, name), migrationJSON(map[string]string{"plan_sha256": hash}), 0600)
}
func validMigrationEntry(e MigrationEntry) bool {
	if e.Path == "" || e.Path == "." || strings.Contains(e.Path, "\\") || strings.Contains(e.Path, ":") || !filepath.IsLocal(e.Path) || filepath.ToSlash(filepath.Clean(e.Path)) != e.Path || migrationExcluded(e.Path) || e.Mode > 0777 || e.Size < 0 || e.Size > migrationMaxFile {
		return false
	}
	return e.Directory && e.Size == 0 && e.SHA256 == "" || !e.Directory && stateformat.Digest(e.SHA256)
}
func validateMigrationPlan(dir string, p MigrationPlan) error {
	if p.Schema != "state-migration-plan/v1" || len(p.Entries) > migrationMaxEntries || p.Target.Schema != "state-format/v2" || p.Target.FormatVersion != 2 || p.Target.MinReader != 2 || p.Target.MinWriter != 2 || p.Target.DirectoryID != p.DirectoryID || p.Target.InstanceID != p.InstanceID {
		return errors.New("state-migrate: invalid plan")
	}
	if _, e := stateformat.Decode(migrationJSON(p.Target)); e != nil {
		return errors.New("state-migrate: invalid target")
	}
	if e := stateformat.ValidateBinding(dir, p.Target); e != nil {
		return errors.New("state-migrate: instance or directory mismatch")
	}
	last := ""
	var total int64
	for _, row := range p.Entries {
		if !validMigrationEntry(row) || row.Path <= last {
			return errors.New("state-migrate: invalid manifest entry")
		}
		last = row.Path
		total += row.Size
	}
	if total > migrationMaxBytes {
		return errors.New("state-migrate: invalid manifest budget")
	}
	if p.SourceMarker != "absent" && !stateformat.Digest(p.SourceMarker) {
		return errors.New("state-migrate: invalid source marker")
	}
	return nil
}
func verifyMigrationSource(dir string, p MigrationPlan) error {
	actual, e := snapshotMigration(dir)
	if e != nil {
		return e
	}
	withoutMarker := func(rows []MigrationEntry) []MigrationEntry {
		out := []MigrationEntry{}
		for _, r := range rows {
			if r.Path != stateformat.MarkerName {
				out = append(out, r)
			}
		}
		return out
	}
	if !reflect.DeepEqual(withoutMarker(actual), withoutMarker(p.Entries)) {
		return errors.New("state-migrate: source data changed; retain state and backup")
	}
	raw, e := migrationReadRegular(filepath.Join(dir, stateformat.MarkerName), stateformat.Budget)
	if errors.Is(e, os.ErrNotExist) {
		if p.SourceMarker == "absent" {
			return nil
		}
		// Some filesystems may lose the directory entry across a failed rename.
		// Only a completed backup and the exact prepared target authorize recovery.
		cp, ce := migrationReadRegular(filepath.Join(dir, stateformat.MigrationDir, "backup.done.json"), 4096)
		staged, se := migrationReadRegular(filepath.Join(dir, stateformat.MigrationDir, "target.json"), 4096)
		var proof struct {
			Plan string `json:"plan_sha256"`
		}
		if ce == nil && se == nil && stateformat.DecodeObject(cp, []string{"plan_sha256"}, &proof) == nil && proof.Plan == stateformat.Hash(migrationJSON(p)) && string(staged) == string(migrationJSON(p.Target)) {
			return nil
		}
	}
	if e != nil {
		return errors.New("state-migrate: source marker unreadable")
	}
	digest := stateformat.Hash(raw)
	if digest != p.SourceMarker && digest != stateformat.Hash(migrationJSON(p.Target)) {
		return errors.New("state-migrate: source marker changed")
	}
	return nil
}

// MigrateState is explicit and supports only the existing initialized v1 family
// to the instance-bound v2 envelope. It never restores or rewrites business data.
func (s *Store) MigrateState(version string) (MigrationResult, error) {
	return s.migrateState(version, nil)
}

// fault is only an internal test seam, never runtime configuration.
func (s *Store) migrateState(version string, fault func(string) error) (result MigrationResult, resultErr error) {
	if err := stateformat.ValidatePath(s.Dir); err != nil {
		return result, err
	}
	if raw, err := migrationReadRegular(filepath.Join(s.Dir, stateformat.PlanName), 8<<20); err == nil {
		var header struct {
			Schema string `json:"schema"`
		}
		if json.Unmarshal(raw, &header) == nil && header.Schema == stateformat.WindowsProfilePlanSchema {
			return result, stateformat.Fail(stateformat.ErrWindowsProfileMigration)
		}
	}
	fail := func(at string) error {
		if fault != nil {
			return fault(at)
		}
		return nil
	}
	result = MigrationResult{Schema: "local-state-migration-result/v1", Status: "migrated", Format: 2}
	if e := RequireStateCompatibility(s.Dir); e == nil {
		if m, e := stateformat.ReadMarker(s.Dir); e == nil && m.Schema == "state-format/v2" {
			if _, e := os.Lstat(filepath.Join(s.Dir, stateformat.PlanName)); errors.Is(e, os.ErrNotExist) {
				result.Status = "up_to_date"
				return result, nil
			}
		}
	}
	planPath := filepath.Join(s.Dir, filepath.FromSlash(stateformat.PlanName))
	_, planErr := os.Lstat(planPath)
	if errors.Is(planErr, os.ErrNotExist) {
		if e := RequireStateCompatibility(s.Dir); e != nil {
			return result, e
		}
		if m, e := stateformat.ReadMarker(s.Dir); e == nil && m.Schema == "state-format/v2" {
			result.Status = "up_to_date"
			return result, nil
		}
	}
	check := func() error { return stateformat.Check(s.Dir, true, true) }
	var locks []*Writer
	defer func() {
		for i := len(locks) - 1; i >= 0; i-- {
			resultErr = errors.Join(resultErr, locks[i].Release())
		}
	}()
	for _, scope := range []string{"", "service-control", "adapter-write", "client-releases", "client-snapshots"} {
		w, e := acquireWriterChecked(filepath.Join(s.Dir, scope), s.Dir, check)
		if e != nil {
			return result, e
		}
		locks = append(locks, w)
	}
	var plan MigrationPlan
	raw, e := migrationReadRegular(planPath, 8<<20)
	if errors.Is(e, os.ErrNotExist) {
		target, e := s.newFormatMarker(version)
		if e != nil {
			return result, errors.New("state-migrate: initialized local instance required; run init first")
		}
		entries, e := snapshotMigration(s.Dir)
		if e != nil {
			return result, e
		}
		source := "absent"
		if b, e := migrationReadRegular(filepath.Join(s.Dir, stateformat.MarkerName), stateformat.Budget); e == nil {
			source = stateformat.Hash(b)
		} else if !errors.Is(e, os.ErrNotExist) {
			return result, e
		}
		plan = MigrationPlan{Schema: "state-migration-plan/v1", DirectoryID: target.DirectoryID, InstanceID: target.InstanceID, SourceMarker: source, Target: target, Entries: entries}
		if e = validateMigrationPlan(s.Dir, plan); e != nil {
			return result, e
		}
		// A directory left before publication may be empty; never adopt unknown data.
		journal := filepath.Join(s.Dir, stateformat.MigrationDir)
		if list, e := os.ReadDir(journal); e == nil {
			for _, entry := range list {
				if entry.Name() != "tmp" || !entry.IsDir() {
					return result, errors.New("state-migrate: unowned journal directory")
				}
			}
			if e := stateformat.CheckParents(filepath.Join(journal, "tmp")); e != nil {
				return result, e
			}
		}
		if e = migrationPrivateDir(journal); e != nil {
			return result, e
		}
		raw = migrationJSON(plan)
		if e = migrationPublish(s.Dir, planPath, raw, 0600); e != nil {
			return result, e
		}
	} else if e != nil {
		return result, errors.New("state-migrate: unreadable plan")
	}
	if e = stateformat.DecodeObject(raw, []string{"schema", "state_directory_id", "instance_id", "source_marker_sha256", "target", "entries"}, &plan); e != nil {
		return result, e
	}
	// Require canonical typed round-trip to reject unknown/duplicate nested fields.
	if string(raw) != string(migrationJSON(plan)) {
		return result, errors.New("state-migrate: noncanonical plan")
	}
	if e = validateMigrationPlan(s.Dir, plan); e != nil {
		return result, e
	}
	digest := stateformat.Hash(raw)
	// A crash after done need not compare an obsolete business snapshot. The
	// completed target and archived plan are verified before removing the barrier.
	if e := stateformat.Check(s.Dir, true, false); e == nil {
		if m, e := stateformat.ReadMarker(s.Dir); e == nil && m.Schema == "state-format/v2" {
			if e = s.finishMigrationBarrier(raw); e != nil {
				return result, e
			}
			result.Status = "up_to_date"
			result.Files = len(plan.Entries)
			return result, nil
		}
	}
	if e = fail("plan"); e != nil {
		return result, e
	}
	if e = verifyMigrationSource(s.Dir, plan); e != nil {
		return result, e
	}
	backup := filepath.Join(s.Dir, stateformat.MigrationDir, "backup")
	if e = migrationPrivateDir(backup); e != nil {
		return result, e
	}
	for i, row := range plan.Entries {
		dest := filepath.Join(backup, filepath.FromSlash(row.Path))
		if row.Directory {
			e = migrationMkdir(dest, 0700)
		} else {
			b, re := migrationReadRegular(dest, migrationMaxFile)
			if errors.Is(re, os.ErrNotExist) {
				b, re = migrationReadRegular(filepath.Join(s.Dir, filepath.FromSlash(row.Path)), migrationMaxFile)
			}
			if re != nil || int64(len(b)) != row.Size || stateformat.Hash(b) != row.SHA256 {
				return result, errors.New("state-migrate: backup or source integrity mismatch")
			}
			e = migrationPublish(s.Dir, dest, b, os.FileMode(row.Mode))
		}
		if e != nil {
			return result, e
		}
		if e = fail(fmt.Sprintf("backup:%d", i)); e != nil {
			return result, e
		}
	}
	// Restore recorded directory modes only after every child is published.
	for i := len(plan.Entries) - 1; i >= 0; i-- {
		row := plan.Entries[i]
		if row.Directory {
			p := filepath.Join(backup, filepath.FromSlash(row.Path))
			if e = os.Chmod(p, os.FileMode(row.Mode)); e != nil {
				return result, e
			}
			if e = migrationSync(p); e != nil {
				return result, e
			}
		}
	}
	// Verify the backup's full file set, bytes and modes (no unknown extra files).
	got, e := snapshotMigrationTree(backup, false)
	if e != nil || !reflect.DeepEqual(got, plan.Entries) {
		return result, errors.New("state-migrate: backup manifest mismatch")
	}
	if e = migrationCheckpoint(s.Dir, "backup.done.json", digest); e != nil {
		return result, e
	}
	if e = fail("backup"); e != nil {
		return result, e
	}
	if e = verifyMigrationSource(s.Dir, plan); e != nil {
		return result, e
	}
	target := migrationJSON(plan.Target)
	live := filepath.Join(s.Dir, stateformat.MarkerName)
	existing, re := migrationReadRegular(live, stateformat.Budget)
	if re != nil && !errors.Is(re, os.ErrNotExist) {
		return result, re
	}
	if string(existing) != string(target) {
		// Prepared target is immutable; rename only the validated compatibility marker.
		staged := filepath.Join(s.Dir, stateformat.MigrationDir, "target.json")
		if e = migrationPublish(s.Dir, staged, target, 0600); e != nil {
			return result, e
		}
		if e = fail("before-marker"); e != nil {
			return result, e
		}
		if e = os.Rename(staged, live); e != nil {
			return result, e
		}
		if e = migrationSync(s.Dir); e != nil {
			return result, e
		}
	}
	if e = fail("marker"); e != nil {
		return result, e
	}
	if e = verifyMigrationSource(s.Dir, plan); e != nil {
		return result, e
	}
	if e = migrationPublish(s.Dir, filepath.Join(s.Dir, stateformat.MigrationDir, "plan.json"), raw, 0600); e != nil {
		return result, e
	}
	done := map[string]string{"schema": "state-migration-done/v1", "plan_sha256": digest, "marker_sha256": stateformat.Hash(target)}
	if e = migrationPublish(s.Dir, filepath.Join(s.Dir, stateformat.MigrationDir, "done.json"), migrationJSON(done), 0600); e != nil {
		return result, e
	}
	if e = fail("done"); e != nil {
		return result, e
	}
	if e = s.finishMigrationBarrier(raw); e != nil {
		return result, e
	}
	result.Files = len(plan.Entries)
	return result, nil
}

func (s *Store) finishMigrationBarrier(raw []byte) error {
	if e := stateformat.Check(s.Dir, true, false); e != nil {
		return e
	}
	archive, e := migrationReadRegular(filepath.Join(s.Dir, stateformat.MigrationDir, "plan.json"), 8<<20)
	if e != nil || string(archive) != string(raw) {
		return errors.New("state-migrate: archived plan mismatch")
	}
	active := filepath.Join(s.Dir, stateformat.PlanName)
	current, e := migrationReadRegular(active, 8<<20)
	if e != nil || string(current) != string(raw) {
		return errors.New("state-migrate: active plan changed")
	}
	if e = os.Remove(active); e != nil {
		return e
	}
	return migrationSync(filepath.Dir(active))
}
