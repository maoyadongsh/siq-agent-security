package skillinstall

import (
	"context"
	"errors"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

// Update-check scheduling metadata lives beside, never inside, the signed
// installation records: saving or reading it must not touch any install
// state. The record is user-controlled source retention for automatic checks
// (N03); automatic checking itself stays read-only and gated behind the
// explicit update-comparison flow.
const updateScheduleSchema = "local-skill-update-schedule/v1"
const updateScheduleViewSchema = "local-skill-update-schedule-view/v1"
const updateSourceSaveSchema = "local-skill-update-source-save/v1"
const updateSourceDisableSchema = "local-skill-update-source-disable/v1"

// Stable update-check states. "checking" is transient and is never persisted
// as last_status; a failed check must never leave up_to_date behind.
const (
	UpdateStatusNotChecked        = "not_checked"
	UpdateStatusChecking          = "checking"
	UpdateStatusUpToDate          = "up_to_date"
	UpdateStatusNewVersion        = "new_version"
	UpdateStatusSourceUnavailable = "source_unavailable"
	UpdateStatusUnsupported       = "unsupported"
)

// Source retention states for the schedule view: the locator is saved, the
// install needs the caller to re-provide its source, the source kind can
// never be re-fetched, or the saved record no longer matches this install.
const (
	UpdateSourceSaved       = "saved"
	UpdateSourceNeeded      = "needs_source"
	UpdateSourceUnsupported = "unsupported"
	UpdateSourceStale       = "stale"
)

const defaultUpdateCheckInterval = 24 * time.Hour
const minUpdateCheckInterval = time.Hour
const maxUpdateCheckInterval = 7 * 24 * time.Hour

var updateSourceSlot = make(chan struct{}, 1)

var updateFailureCategories = map[string]bool{
	"source_unavailable": true,
	"url_blocked":        true,
	"changed":            true,
	"limit":              true,
	"invalid":            true,
	"unavailable":        true,
	"canceled":           true,
}

type UpdateSourceRequest struct {
	SchemaVersion string `json:"schema_version"`
	RemoteURL     string `json:"remote_url"`
	Enable        bool   `json:"enable"`
	ActorID       string `json:"actor_id"`
}

// UpdateSourceDisableRequest deliberately has no locator field. Disabling an
// already saved source is authorized only by the current signed schedule
// record; callers cannot use this path to replace or repair that record.
type UpdateSourceDisableRequest struct {
	SchemaVersion string `json:"schema_version"`
	ActorID       string `json:"actor_id"`
}

var ErrUpdateSourceNotConfigured = errors.New("skill_update_source_not_configured")

// UpdateSchedule is the persisted per-install update-check metadata. Locator
// keeps only the public ZIP locator (https, no userinfo, no query string):
// private or temporary authentication references — including any query-borne
// token — are never persisted, and Display carries only scheme://host/path so
// no sensitive URL reaches disk, API views or audit.
type UpdateSchedule struct {
	SchemaVersion        string `json:"schema_version"`
	InstallID            string `json:"install_id"`
	SourceKind           string `json:"source_kind"`
	Locator              string `json:"locator,omitempty"`
	Display              string `json:"display"`
	Enabled              bool   `json:"enabled"`
	IntervalSeconds      int    `json:"interval_seconds"`
	InstallBindingDigest string `json:"install_binding_digest"`
	NextCheckAt          string `json:"next_check_at,omitempty"`
	LastAttemptAt        string `json:"last_attempt_at,omitempty"`
	LastSuccessAt        string `json:"last_success_at,omitempty"`
	LastStatus           string `json:"last_status"`
	FailureCategory      string `json:"failure_category,omitempty"`
	FailureCount         int    `json:"failure_count,omitempty"`
	SavedBy              string `json:"saved_by"`
	UpdatedAt            string `json:"updated_at"`
	Signature            string `json:"signature"`
}

type UpdateScheduleView struct {
	SchemaVersion   string `json:"schema_version"`
	InstallID       string `json:"install_id"`
	SourceKind      string `json:"source_kind"`
	Display         string `json:"display"`
	Enabled         bool   `json:"enabled"`
	SourceState     string `json:"source_state"`
	Status          string `json:"status"`
	FailureCategory string `json:"failure_category,omitempty"`
	NextCheckAt     string `json:"next_check_at,omitempty"`
	LastAttemptAt   string `json:"last_attempt_at,omitempty"`
	LastSuccessAt   string `json:"last_success_at,omitempty"`
}

func (s *Store) updateSourcePath(id string) string {
	return filepath.Join(s.dir, "update-sources", id+".json")
}

// installBindingDigest binds schedule metadata to this exact installed
// object (source digests + plan signature), so a late or replayed schedule
// write can never land on a reinstalled or replaced install.
func installBindingDigest(record *Record) (string, error) {
	raw, err := canon.Marshal(map[string]any{
		"artifact_digest": record.Plan.Source.ArtifactDigest,
		"analysis_sha256": record.Plan.Source.AnalysisSHA256,
		"plan_signature":  record.Plan.Signature,
	})
	if err != nil {
		return "", ErrInvalid
	}
	return hash(raw), nil
}

// locatorDisplay reduces a locator to scheme://host/path. Userinfo, query and
// fragment are dropped: the display form is safe to persist and show, while
// the fetchable locator (if any) stays in Locator under the public-locator
// rules.
func locatorDisplay(raw string) string {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" || len(raw) > 4096 {
		return ""
	}
	shown := url.URL{Scheme: parsed.Scheme, Host: parsed.Host, Path: parsed.Path}
	display := shown.String()
	if display == "" || len(display) > 512 || !utf8.ValidString(display) || strings.IndexFunc(display, isControlRune) >= 0 {
		return ""
	}
	return display
}

func isControlRune(r rune) bool { return r < 0x20 || r == 0x7f }

func (sched *UpdateSchedule) validate() error {
	if sched.SchemaVersion != updateScheduleSchema || !validInstallID(sched.InstallID) || (sched.SourceKind != "git" && sched.SourceKind != "https_zip") || !displayValid(sched.Display) || !actorIDValid(sched.SavedBy) || !digestPattern.MatchString(sched.InstallBindingDigest) || sched.FailureCount < 0 || sched.FailureCount > 63 || len(sched.FailureCategory) > 64 || !utf8.ValidString(sched.FailureCategory) || strings.IndexFunc(sched.FailureCategory, isControlRune) >= 0 {
		return ErrInvalid
	}
	if sched.FailureCount > 0 && sched.FailureCategory == "" {
		// A failure count without a category cannot be explained to the user.
		return ErrInvalid
	}
	if sched.IntervalSeconds < int(minUpdateCheckInterval.Seconds()) || sched.IntervalSeconds > int(maxUpdateCheckInterval.Seconds()) {
		return ErrInvalid
	}
	switch sched.LastStatus {
	case UpdateStatusNotChecked, UpdateStatusUpToDate, UpdateStatusNewVersion, UpdateStatusSourceUnavailable, UpdateStatusUnsupported:
	case UpdateStatusChecking:
		return ErrInvalid
	default:
		return ErrInvalid
	}
	if (sched.LastStatus == UpdateStatusUpToDate || sched.LastStatus == UpdateStatusNewVersion) && sched.LastSuccessAt == "" {
		// A failed check must never be presented as "up to date".
		return ErrInvalid
	}
	if sched.FailureCategory != "" && !updateFailureCategories[sched.FailureCategory] {
		return ErrInvalid
	}
	for _, value := range []string{sched.NextCheckAt, sched.LastAttemptAt, sched.LastSuccessAt} {
		if value == "" {
			continue
		}
		if _, err := time.Parse(time.RFC3339Nano, value); err != nil {
			return ErrInvalid
		}
	}
	if sched.SourceKind == "https_zip" && sched.Locator != "" {
		parsed, err := url.Parse(sched.Locator)
		if err != nil || parsed.Scheme != "https" || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
			return ErrInvalid
		}
	}
	if sched.SourceKind == "git" && sched.Locator != "" {
		return ErrInvalid
	}
	return nil
}

// SaveUpdateSource records (or disables) the user-retained source reference
// for automatic update checks. It is the only writer of schedule metadata and
// shares CheckUpdate's preconditions: a completed, not-yet-verified install
// whose import record still binds. It writes nothing outside update-sources/.
func (s *Store) SaveUpdateSource(ctx context.Context, id string, req UpdateSourceRequest) (*UpdateSchedule, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if req.SchemaVersion != updateSourceSaveSchema || len(req.RemoteURL) > 4096 || !utf8.ValidString(req.RemoteURL) || !actorIDValid(req.ActorID) {
		return nil, ErrInvalid
	}
	select {
	case updateSourceSlot <- struct{}{}:
		defer func() { <-updateSourceSlot }()
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	record, installed, err := s.historicalRecord(ctx, id)
	if err != nil {
		return nil, err
	}
	if record.RecordedStatus != "installed_unverified" || record.Operation == nil {
		return nil, ErrChanged
	}
	if err := s.removalStarted(id); err != nil {
		return nil, err
	}
	imported, err := s.imports.ReadRecord(ctx, installed.Plan.Source.ImportID)
	if err != nil {
		return nil, sourceError(ctx, err)
	}
	if imported.ArtifactDigest != installed.Plan.Source.ArtifactDigest || imported.AnalysisSHA256 != installed.Plan.Source.AnalysisSHA256 {
		return nil, ErrChanged
	}
	// Explicit reconfiguration is not a migration or repair operation. Keep
	// unknown or damaged records intact, including when merely disabling checks.
	// All schedule writers use updateSourceSlot, held through replacement below.
	if _, err := s.readUpdateSchedule(ctx, id); err != nil {
		return nil, err
	}
	sched := &UpdateSchedule{
		SchemaVersion:   updateScheduleSchema,
		InstallID:       id,
		SourceKind:      imported.SourceKind,
		Display:         "",
		Enabled:         req.Enable,
		IntervalSeconds: int(defaultUpdateCheckInterval.Seconds()),
		LastStatus:      UpdateStatusNotChecked,
		SavedBy:         req.ActorID,
		UpdatedAt:       s.now().UTC().Format(time.RFC3339Nano),
	}
	switch imported.SourceKind {
	case "git":
		// The signed record already carries the URL; a caller-supplied one
		// must not be able to redirect the check.
		if req.RemoteURL != "" {
			return nil, ErrInvalid
		}
		if sched.Display = locatorDisplay(imported.Git.URL); sched.Display == "" {
			return nil, ErrInvalid
		}
	case "https_zip":
		if req.RemoteURL == "" {
			return nil, ErrInvalid
		}
		canonical, err := skillimport.ZipSourceBinding(imported, req.RemoteURL)
		if err != nil {
			return nil, updateFetchError(ctx, err)
		}
		parsed, err := url.Parse(canonical)
		if err != nil || parsed.RawQuery != "" {
			// Query strings are treated as private or temporary
			// authentication references and are never persisted.
			return nil, ErrInvalid
		}
		sched.Locator = canonical
		if sched.Display = locatorDisplay(canonical); sched.Display == "" {
			return nil, ErrInvalid
		}
	default:
		// local_dir/local_zip imports have no fetchable upstream.
		return nil, ErrInvalid
	}
	binding, err := installBindingDigest(record)
	if err != nil {
		return nil, err
	}
	sched.InstallBindingDigest = binding
	if req.Enable {
		sched.NextCheckAt = s.now().UTC().Add(defaultUpdateCheckInterval).Format(time.RFC3339Nano)
	}
	doc, err := document(*sched, false)
	if err != nil {
		return nil, err
	}
	sched.Signature, err = s.key.SignCanonical(doc)
	if err != nil {
		return nil, ErrUnavailable
	}
	if err = replaceDocument(s.updateSourcePath(id), *sched); err != nil {
		return nil, err
	}
	return sched, nil
}

// DisableUpdateSource stops automatic checks using only the current signed
// source record. It preserves the locator, display and install binding, never
// accepts caller-supplied source material, and is byte-idempotent after the
// first successful disable. Unknown, damaged or stale records are left intact.
func (s *Store) DisableUpdateSource(ctx context.Context, id string, req UpdateSourceDisableRequest) (*UpdateSchedule, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if req.SchemaVersion != updateSourceDisableSchema || !actorIDValid(req.ActorID) || !validInstallID(id) {
		return nil, ErrInvalid
	}
	select {
	case updateSourceSlot <- struct{}{}:
		defer func() { <-updateSourceSlot }()
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	record, installed, err := s.historicalRecord(ctx, id)
	if err != nil {
		return nil, err
	}
	if record.RecordedStatus != "installed_unverified" || record.Operation == nil {
		return nil, ErrChanged
	}
	if err := s.removalStarted(id); err != nil {
		return nil, err
	}
	imported, err := s.imports.ReadRecord(ctx, installed.Plan.Source.ImportID)
	if err != nil {
		return nil, sourceError(ctx, err)
	}
	if imported.ArtifactDigest != installed.Plan.Source.ArtifactDigest || imported.AnalysisSHA256 != installed.Plan.Source.AnalysisSHA256 {
		return nil, ErrChanged
	}
	sched, err := s.readUpdateSchedule(ctx, id)
	if err != nil {
		return nil, err
	}
	if sched == nil {
		return nil, ErrUpdateSourceNotConfigured
	}
	binding, err := installBindingDigest(record)
	if err != nil {
		return nil, err
	}
	if sched.SourceKind != imported.SourceKind || sched.InstallBindingDigest != binding {
		return nil, ErrChanged
	}
	switch sched.SourceKind {
	case "git":
		if sched.Locator != "" || sched.Display != locatorDisplay(imported.Git.URL) {
			return nil, ErrChanged
		}
	case "https_zip":
		canonical, bindErr := skillimport.ZipSourceBinding(imported, sched.Locator)
		if bindErr != nil || canonical != sched.Locator || sched.Display != locatorDisplay(canonical) {
			return nil, ErrChanged
		}
	default:
		return nil, ErrChanged
	}
	if !sched.Enabled {
		// Retrying after a lost response must not change timestamps, signatures
		// or attribution. The signed disabled record is already the result.
		copy := *sched
		return &copy, nil
	}
	sched.Enabled = false
	sched.NextCheckAt = ""
	sched.LastAttemptAt = ""
	sched.LastSuccessAt = ""
	sched.LastStatus = UpdateStatusNotChecked
	sched.FailureCategory = ""
	sched.FailureCount = 0
	sched.SavedBy = req.ActorID
	sched.UpdatedAt = s.now().UTC().Format(time.RFC3339Nano)
	doc, err := document(*sched, false)
	if err != nil {
		return nil, err
	}
	sched.Signature, err = s.key.SignCanonical(doc)
	if err != nil {
		return nil, ErrUnavailable
	}
	if err := replaceDocument(s.updateSourcePath(id), *sched); err != nil {
		return nil, err
	}
	return sched, nil
}

// replaceDocument atomically writes value over an existing path. Unlike
// publishDocument it may overwrite: re-saving an update source is an explicit
// user action on the caller-designated schedule file only.
func replaceDocument(path string, value any) error {
	if err := privateDirectory(filepath.Dir(path)); err != nil {
		return err
	}
	if err := checkExistingPrivateMetadata(path); err != nil {
		return err
	}
	doc, err := document(value, true)
	if err != nil {
		return ErrUnavailable
	}
	raw, err := canon.Marshal(doc)
	if err != nil {
		return ErrUnavailable
	}
	f, err := statefs.CreatePrivateTemp(filepath.Dir(path), ".operation-*")
	if err != nil {
		return ErrUnavailable
	}
	name := f.Name()
	defer statefs.Remove(name)
	if _, err = f.Write(raw); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil || closeErr != nil {
		return ErrUnavailable
	}
	if err := checkExistingPrivateMetadata(path); err != nil {
		return err
	}
	if err := statefs.Rename(name, path); err != nil {
		return ErrUnavailable
	}
	return nil
}

// readUpdateSchedule validates the signed schedule record, or reports a
// missing one as nil without treating that as an error.
func (s *Store) readUpdateSchedule(ctx context.Context, id string) (*UpdateSchedule, error) {
	// A missing update-sources entry (or directory) simply means no source
	// has been saved yet; readSigned fail-closes on anything else.
	if _, err := os.Lstat(s.updateSourcePath(id)); os.IsNotExist(err) {
		return nil, nil
	}
	var sched UpdateSchedule
	if err := s.readSigned(ctx, s.updateSourcePath(id), &sched); err != nil {
		if errors.Is(err, ErrNotFound) {
			return nil, nil
		}
		return nil, err
	}
	if sched.InstallID != id || sched.Signature == "" || !signaturePattern.MatchString(sched.Signature) {
		return nil, ErrChanged
	}
	if err := sched.validate(); err != nil {
		return nil, ErrChanged
	}
	return &sched, nil
}

// ReadUpdateSchedule answers "what does automatic checking currently know
// about this install?" without fetching anything and without requiring a
// saved source. Stale metadata (bound to a different install object) is
// reported as stale rather than leaked.
func (s *Store) ReadUpdateSchedule(ctx context.Context, id string) (*UpdateScheduleView, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if !validInstallID(id) {
		return nil, ErrInvalid
	}
	record, _, err := s.historicalRecord(ctx, id)
	if err != nil {
		return nil, err
	}
	if err := s.removalStarted(id); err != nil {
		return nil, err
	}
	imported, err := s.imports.ReadRecord(ctx, record.Plan.Source.ImportID)
	if err != nil {
		return nil, sourceError(ctx, err)
	}
	view := &UpdateScheduleView{SchemaVersion: updateScheduleViewSchema, InstallID: id, SourceKind: imported.SourceKind, Status: UpdateStatusNotChecked}
	if imported.SourceKind != "git" && imported.SourceKind != "https_zip" {
		view.SourceState = UpdateSourceUnsupported
		view.Status = UpdateStatusUnsupported
		return view, nil
	}
	view.SourceState = UpdateSourceNeeded
	saved, err := s.readUpdateSchedule(ctx, id)
	if err != nil {
		return nil, err
	}
	if saved == nil {
		return view, nil
	}
	binding, err := installBindingDigest(record)
	if err != nil {
		return nil, err
	}
	if saved.InstallID != id || saved.SourceKind != imported.SourceKind || saved.InstallBindingDigest != binding {
		view.SourceState = UpdateSourceStale
		return view, nil
	}
	view.SourceState = UpdateSourceSaved
	view.Display = saved.Display
	view.Enabled = saved.Enabled
	view.Status = saved.LastStatus
	view.FailureCategory = saved.FailureCategory
	view.NextCheckAt = saved.NextCheckAt
	view.LastAttemptAt = saved.LastAttemptAt
	view.LastSuccessAt = saved.LastSuccessAt
	return view, nil
}

// writeScheduleUpdate rewrites the saved schedule record through mutate. It is
// a no-op when no record exists, the install is gone or under removal, or the
// record no longer binds to this exact install object — so a late or replayed
// outcome can never land on a reinstalled install. Callers must already hold
// stageSlot (SaveUpdateSource excepted) so gate ordering stays
// stageSlot → updateSourceSlot everywhere.
func (s *Store) writeScheduleUpdate(ctx context.Context, id string, mutate func(*UpdateSchedule, time.Time), expectedSignature string) error {
	select {
	case updateSourceSlot <- struct{}{}:
		defer func() { <-updateSourceSlot }()
	case <-ctx.Done():
		return ctx.Err()
	}
	sched, err := s.readUpdateSchedule(ctx, id)
	if err != nil || sched == nil {
		return err
	}
	if sched.Signature != expectedSignature {
		return ErrChanged
	}
	record, installed, err := s.historicalRecord(ctx, id)
	if err != nil || record.RecordedStatus != "installed_unverified" || installed == nil {
		return nil
	}
	if s.removalStarted(id) != nil {
		return nil
	}
	binding, err := installBindingDigest(record)
	if err != nil || binding != sched.InstallBindingDigest {
		return nil
	}
	now := s.now().UTC()
	mutate(sched, now)
	sched.UpdatedAt = now.Format(time.RFC3339Nano)
	if err := sched.validate(); err != nil {
		return ErrChanged
	}
	doc, err := document(*sched, false)
	if err != nil {
		return err
	}
	signature, err := s.key.SignCanonical(doc)
	if err != nil {
		return ErrUnavailable
	}
	sched.Signature = signature
	return replaceDocument(s.updateSourcePath(id), *sched)
}

// updateFailureOf maps a check error to its bounded failure category. The
// second result reports whether the outcome should be recorded at all:
// removal-pending and unknown-install refusals leave schedule metadata alone.
func updateFailureOf(err error) (string, string, bool) {
	switch {
	case errors.Is(err, ErrRemovalPending), errors.Is(err, ErrNotFound):
		return "", "", false
	case errors.Is(err, ErrUpdateSourceUnavailable):
		return UpdateStatusSourceUnavailable, "source_unavailable", true
	case errors.Is(err, ErrUpdateURLBlocked):
		return UpdateStatusSourceUnavailable, "url_blocked", true
	case errors.Is(err, ErrLimit):
		return UpdateStatusSourceUnavailable, "limit", true
	case errors.Is(err, ErrChanged):
		return UpdateStatusSourceUnavailable, "changed", true
	case errors.Is(err, ErrInvalid):
		return UpdateStatusSourceUnavailable, "invalid", true
	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
		return UpdateStatusSourceUnavailable, "canceled", true
	default:
		return UpdateStatusSourceUnavailable, "unavailable", true
	}
}
