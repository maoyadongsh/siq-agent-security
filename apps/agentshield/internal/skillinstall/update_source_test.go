package skillinstall

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
)

func saveRequest(url string, enable bool) UpdateSourceRequest {
	return UpdateSourceRequest{SchemaVersion: "local-skill-update-source-save/v1", RemoteURL: url, Enable: enable, ActorID: "human"}
}

func disableRequest() UpdateSourceDisableRequest {
	return UpdateSourceDisableRequest{SchemaVersion: "local-skill-update-source-disable/v1", ActorID: "human-disabler"}
}

// TestSaveUpdateSourceGitAndZeroInstallWrites covers the happy git path: the
// schedule record is signed and stored under update-sources/ only, and no
// installation state file appears.
func TestSaveUpdateSourceGitAndZeroInstallWrites(t *testing.T) {
	f, op := installedInspection(t)
	s := f.store
	gitifyImportRecord(t, f)
	root := filepath.Join(f.store.dir)
	before := storeTree(t, root)
	if _, err := s.SaveUpdateSource(context.Background(), "sin-"+strings.Repeat("a", 64), saveRequest("", true)); !errors.Is(err, ErrNotFound) {
		t.Fatal("unknown install accepted", err)
	}
	sched, err := s.SaveUpdateSource(context.Background(), op.InstallID, saveRequest("", true))
	if err != nil {
		t.Fatal(err)
	}
	if sched.SourceKind != "git" || sched.Locator != "" || sched.Display != gitFixtureURL || !sched.Enabled || sched.IntervalSeconds != 86400 || sched.LastStatus != UpdateStatusNotChecked || sched.NextCheckAt == "" || sched.SavedBy != "human" || sched.Signature == "" {
		t.Fatalf("unexpected schedule %+v", sched)
	}
	after := storeTree(t, root)
	for _, key := range extraKeys(before, after) {
		if !strings.HasPrefix(key, filepath.Join("update-sources", "")) {
			t.Fatal("save wrote outside update-sources/", key)
		}
	}
	view, err := s.ReadUpdateSchedule(context.Background(), op.InstallID)
	if err != nil {
		t.Fatal(err)
	}
	if view.SourceState != UpdateSourceSaved || view.Status != UpdateStatusNotChecked || view.Display != gitFixtureURL || view.SchemaVersion != "local-skill-update-schedule-view/v1" || view.Enabled != true {
		t.Fatalf("unexpected view %+v", view)
	}
	if strings.Contains(view.Display, "?") || strings.Contains(view.Display, "@") {
		t.Fatal("display leaks credentials")
	}
}

func TestSaveUpdateSourceZipBinding(t *testing.T) {
	f, op := installedInspection(t)
	s := f.store
	zipifyImportRecord(t, f)
	id := op.InstallID
	// A URL that does not reproduce the import's locator digest is refused.
	if _, err := s.SaveUpdateSource(context.Background(), id, saveRequest("https://download.example.com/other.zip", true)); !errors.Is(err, ErrChanged) {
		t.Fatal("unbound URL accepted", err)
	}
	// A query string is a private/temporary reference and is never persisted.
	if _, err := s.SaveUpdateSource(context.Background(), id, saveRequest(zipFixtureURL+"?token=secret", true)); !errors.Is(err, ErrChanged) {
		t.Fatal("query URL accepted", err)
	}
	// The original URL still binds and is saved as the public locator.
	sched, err := s.SaveUpdateSource(context.Background(), id, saveRequest(zipFixtureURL, true))
	if err != nil {
		t.Fatal(err)
	}
	if sched.SourceKind != "https_zip" || sched.Locator != zipFixtureURL || sched.Display != zipFixtureURL {
		t.Fatalf("unexpected schedule %+v", sched)
	}
	view, err := s.ReadUpdateSchedule(context.Background(), id)
	if err != nil {
		t.Fatal(err)
	}
	if view.SourceState != UpdateSourceSaved || view.SourceKind != "https_zip" {
		t.Fatalf("unexpected view %+v", view)
	}
}

func TestDisableUpdateSourceUsesSavedZIPAndIsByteIdempotent(t *testing.T) {
	f, op := installedInspection(t)
	s := f.store
	zipifyImportRecord(t, f)
	if _, err := s.DisableUpdateSource(context.Background(), op.InstallID, disableRequest()); !errors.Is(err, ErrUpdateSourceNotConfigured) {
		t.Fatal("missing source was not distinguished", err)
	}
	if _, err := os.Lstat(s.updateSourcePath(op.InstallID)); !os.IsNotExist(err) {
		t.Fatal("missing-source disable created state", err)
	}
	sched, err := s.SaveUpdateSource(context.Background(), op.InstallID, saveRequest(zipFixtureURL, true))
	if err != nil {
		t.Fatal(err)
	}
	path := s.updateSourcePath(op.InstallID)
	pathsBefore := storeTree(t, s.dir)
	locator, display, binding, interval := sched.Locator, sched.Display, sched.InstallBindingDigest, sched.IntervalSeconds
	disabled, err := s.DisableUpdateSource(context.Background(), op.InstallID, disableRequest())
	if err != nil {
		t.Fatal(err)
	}
	if disabled.Enabled || disabled.NextCheckAt != "" || disabled.LastAttemptAt != "" || disabled.LastSuccessAt != "" || disabled.LastStatus != UpdateStatusNotChecked || disabled.FailureCategory != "" || disabled.FailureCount != 0 {
		t.Fatalf("disable did not clear scheduling outcome: %+v", disabled)
	}
	if disabled.Locator != locator || disabled.Display != display || disabled.InstallBindingDigest != binding || disabled.IntervalSeconds != interval || disabled.SavedBy != "human-disabler" {
		t.Fatalf("disable replaced saved source identity: %+v", disabled)
	}
	if !reflect.DeepEqual(pathsBefore, storeTree(t, s.dir)) {
		t.Fatal("disable changed state path listing")
	}
	first, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	replayed, err := s.DisableUpdateSource(context.Background(), op.InstallID, UpdateSourceDisableRequest{SchemaVersion: updateSourceDisableSchema, ActorID: "another-human"})
	if err != nil {
		t.Fatal(err)
	}
	second, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(first, second) {
		t.Fatal("idempotent disable rewrote signed bytes", err)
	}
	if replayed.Signature != disabled.Signature || replayed.SavedBy != "human-disabler" {
		t.Fatal("idempotent disable changed attribution")
	}
}

func TestDisableUpdateSourceRejectsStaleBindingWithoutWrites(t *testing.T) {
	f, op := installedInspection(t)
	s := f.store
	gitifyImportRecord(t, f)
	if _, err := s.SaveUpdateSource(context.Background(), op.InstallID, saveRequest("", true)); err != nil {
		t.Fatal(err)
	}
	path := s.updateSourcePath(op.InstallID)
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	value, err := canon.Decode(before)
	if err != nil {
		t.Fatal(err)
	}
	doc := value.(map[string]any)
	doc["install_binding_digest"] = strings.Repeat("a", 64)
	delete(doc, "signature")
	doc["signature"], err = s.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	stale, err := canon.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, stale, 0600); err != nil {
		t.Fatal(err)
	}
	pathsBefore := storeTree(t, s.dir)
	if _, err := s.DisableUpdateSource(context.Background(), op.InstallID, disableRequest()); !errors.Is(err, ErrChanged) {
		t.Fatal("stale source was disabled", err)
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(stale, after) || !reflect.DeepEqual(pathsBefore, storeTree(t, s.dir)) {
		t.Fatal("rejected stale disable changed state", err)
	}
}

// TestSaveUpdateSourceQueryBorneTokenRejected installs an import whose
// original locator itself carried a temporary token and verifies the save is
// refused outright: private or temporary authentication references never get
// a persistence channel.
func TestSaveUpdateSourceQueryBorneTokenRejected(t *testing.T) {
	f, op := installedInspection(t)
	s := f.store
	tokenURL := zipFixtureURL + "?token=temporary-secret"
	zipifyImportRecord(t, f)
	rewriteImportRecord(t, f, func(doc map[string]any) {
		canonical, err := canon.Marshal(map[string]any{"url": tokenURL, "archive_path": "", "expected_sha256": zipFixtureDigest})
		if err != nil {
			t.Fatal(err)
		}
		doc["source_locator_digest"] = hash(canonical)
	})
	id := op.InstallID
	if _, err := s.SaveUpdateSource(context.Background(), id, saveRequest(tokenURL, true)); !errors.Is(err, ErrInvalid) {
		t.Fatal("token URL accepted for persistence", err)
	}
	view, err := s.ReadUpdateSchedule(context.Background(), id)
	if err != nil {
		t.Fatal(err)
	}
	if view.SourceState != UpdateSourceNeeded || view.Status != UpdateStatusNotChecked {
		t.Fatalf("unexpected view %+v", view)
	}
}

func TestSaveUpdateSourceLocalKindAndPreconditions(t *testing.T) {
	f, op := installedInspection(t)
	s := f.store
	// local_dir imports have no fetchable upstream.
	if _, err := s.SaveUpdateSource(context.Background(), op.InstallID, saveRequest("", true)); !errors.Is(err, ErrInvalid) {
		t.Fatal("local source accepted", err)
	}
	view, err := s.ReadUpdateSchedule(context.Background(), op.InstallID)
	if err != nil {
		t.Fatal(err)
	}
	if view.SourceState != UpdateSourceUnsupported || view.Status != UpdateStatusUnsupported || view.SourceKind != "local_dir" {
		t.Fatalf("unexpected view %+v", view)
	}
	// Git sources refuse a caller-supplied URL.
	gitifyImportRecord(t, f)
	if _, err := s.SaveUpdateSource(context.Background(), op.InstallID, saveRequest("https://evil.example.com/skill.git", true)); !errors.Is(err, ErrInvalid) {
		t.Fatal("git source accepted remote_url", err)
	}
	// A pending removal blocks saves.
	f.revoke(t)
	req := removalRequest(t, s, op.InstallID)
	if _, err := s.Remove(context.Background(), op.InstallID, req); err != nil {
		t.Fatal(err)
	}
	if _, err := s.SaveUpdateSource(context.Background(), op.InstallID, saveRequest("", true)); !errors.Is(err, ErrRemovalPending) {
		t.Fatal("removal pending not reported", err)
	}
	if _, err := s.ReadUpdateSchedule(context.Background(), op.InstallID); !errors.Is(err, ErrRemovalPending) {
		t.Fatal("read allowed during removal", err)
	}
}

func TestSaveUpdateSourceDisableResetsAndRedacts(t *testing.T) {
	f, op := installedInspection(t)
	s := f.store
	gitifyImportRecord(t, f)
	// A tokenized git URL still binds (it comes from the signed record) but
	// the persisted display must drop the query.
	rewriteImportRecord(t, f, func(doc map[string]any) {
		doc["git"].(map[string]any)["url"] = gitFixtureURL + "?token=secret"
		canonical, err := canon.Marshal(map[string]any{"url": gitFixtureURL + "?token=secret", "ref": "", "sub_dir": "", "expected_commit": ""})
		if err != nil {
			t.Fatal(err)
		}
		doc["source_locator_digest"] = hash(canonical)
	})
	if _, err := s.SaveUpdateSource(context.Background(), op.InstallID, saveRequest("", true)); err != nil {
		t.Fatal(err)
	}
	view, err := s.ReadUpdateSchedule(context.Background(), op.InstallID)
	if err != nil {
		t.Fatal(err)
	}
	if view.Display != gitFixtureURL || strings.Contains(view.Display, "token") {
		t.Fatalf("display not redacted: %q", view.Display)
	}
	// Disabling retains the file but stops scheduling and resets status.
	sched, err := s.SaveUpdateSource(context.Background(), op.InstallID, saveRequest("", false))
	if err != nil {
		t.Fatal(err)
	}
	if sched.Enabled || sched.NextCheckAt != "" || sched.LastStatus != UpdateStatusNotChecked || sched.LastSuccessAt != "" {
		t.Fatalf("disable did not reset: %+v", sched)
	}
	view, err = s.ReadUpdateSchedule(context.Background(), op.InstallID)
	if err != nil {
		t.Fatal(err)
	}
	if view.SourceState != UpdateSourceSaved || view.Enabled {
		t.Fatalf("unexpected view %+v", view)
	}
}

// TestReadUpdateScheduleTamperAndInvariants verifies that a modified,
// unknown-fielded or semantically invalid schedule record is refused, and
// that metadata bound to a different install object is reported stale rather
// than applied.
func TestReadUpdateScheduleTamperAndInvariants(t *testing.T) {
	f, op := installedInspection(t)
	s := f.store
	gitifyImportRecord(t, f)
	if _, err := s.SaveUpdateSource(context.Background(), op.InstallID, saveRequest("", true)); err != nil {
		t.Fatal(err)
	}
	path := s.updateSourcePath(op.InstallID)
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	writeSchedule := func(mutate func(map[string]any)) {
		t.Helper()
		value, err := canon.Decode(raw)
		if err != nil {
			t.Fatal(err)
		}
		doc := value.(map[string]any)
		mutate(doc)
		delete(doc, "signature")
		signature, err := f.store.key.SignCanonical(doc)
		if err != nil {
			t.Fatal(err)
		}
		doc["signature"] = signature
		signed, err := canon.Marshal(doc)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, signed, 0600); err != nil {
			t.Fatal(err)
		}
	}
	restore := func() {
		t.Helper()
		if err := os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
	// Statuses never persisted as last_status, and failures are never "up to
	// date" without a success timestamp.
	for _, status := range []string{"checking", "up_to_date", "new_version", "bogus"} {
		writeSchedule(func(doc map[string]any) { doc["last_status"] = status })
		if _, err := s.ReadUpdateSchedule(context.Background(), op.InstallID); !errors.Is(err, ErrChanged) {
			t.Fatal("invalid last_status accepted:", status, err)
		}
	}
	restore()
	// Unknown fields break the canonical round-trip.
	writeSchedule(func(doc map[string]any) { doc["extra"] = true })
	if _, err := s.ReadUpdateSchedule(context.Background(), op.InstallID); !errors.Is(err, ErrChanged) {
		t.Fatal("unknown field accepted", err)
	}
	restore()
	// Interval must stay bounded.
	writeSchedule(func(doc map[string]any) { doc["interval_seconds"] = 60 })
	if _, err := s.ReadUpdateSchedule(context.Background(), op.InstallID); !errors.Is(err, ErrChanged) {
		t.Fatal("unbounded interval accepted", err)
	}
	restore()
	// Metadata bound to another install object is stale, not applied.
	writeSchedule(func(doc map[string]any) { doc["install_binding_digest"] = strings.Repeat("a", 64) })
	view, err := s.ReadUpdateSchedule(context.Background(), op.InstallID)
	if err != nil {
		t.Fatal(err)
	}
	if view.SourceState != UpdateSourceStale || view.Display != "" || view.Status != UpdateStatusNotChecked {
		t.Fatalf("stale metadata leaked: %+v", view)
	}
	restore()
	if _, err := s.ReadUpdateSchedule(context.Background(), op.InstallID); err != nil {
		t.Fatal(err)
	}
}
