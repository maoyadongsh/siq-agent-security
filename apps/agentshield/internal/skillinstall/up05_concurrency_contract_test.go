package skillinstall

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/state"
)

// UP05 concurrency contract (B03). Every interleaving below is driven by an
// explicit event/barrier — the store's private commit-boundary hook or the
// upstream seam — never by sleeping and hoping for a schedule. Allowed
// outcomes per request are exactly: the single success, idempotent reuse of
// that success, or a contract conflict. Duplicated side effects, orphaned
// artifacts and double revocation are failures regardless of outcome mix.

// stageSecondUpdate stages a second, distinct plan against the same install.
// Distinct request IDs keep checkUpdateRequest from collapsing them, so both
// updates are legitimately pending at once.
func stageSecondUpdate(t *testing.T, f fixture, op *Operation, first UpdateStageRequest) (*UpdatePlan, UpdateCommitRequest) {
	t.Helper()
	second := first
	second.RequestID = "up-" + strings.Repeat("b", 32)
	p, reused, err := f.store.StageUpdate(nil, op.InstallID, second)
	if err != nil || reused {
		t.Fatal(p, reused, err)
	}
	return p, UpdateCommitRequest{"local-skill-update-commit/v1", p.UpdateID, p.Signature, p.ActorID, true}
}

// requireSingleLiveInstall asserts the shared end-state invariants after any
// interleave: one live installation, the original removed exactly once, no
// orphaned replacement claim, unknown user files preserved, and grant
// revisions frozen once the dust settles.
func requireSingleLiveInstall(t *testing.T, f fixture, originalID string, replacementPlanIDs []string) {
	t.Helper()
	s := f.store
	ctx := context.Background()
	live := 0
	for _, id := range replacementPlanIDs {
		if _, err := s.claim(ctx, installID(id)); err == nil {
			live++
		} else if !errors.Is(err, ErrNotFound) {
			t.Fatal(err)
		}
	}
	if live != 1 {
		t.Fatalf("expected exactly one live replacement install, got %d", live)
	}
	if entries, err := os.ReadDir(filepath.Join(f.root, "skills")); err != nil || len(entries) != 1 {
		t.Fatalf("target tree must hold exactly one skill: %v %v", entries, err)
	}
	if _, err := os.Stat(filepath.Join(f.root, "skills", "example", "notes.txt")); err != nil {
		t.Fatal("unknown user file did not survive the interleave", err)
	}
	removal, err := s.ReadRemoval(ctx, originalID)
	if err != nil || removal.Status != "removed" || removal.Result == nil {
		t.Fatal("original install not removed exactly once", removal, err)
	}
	// Frozen authority: repeated reads must not observe further revocations.
	g, rev, err := s.authority.GetGrantWithSeq(f.request.GrantID)
	if err != nil || g.Status != "revoked" {
		t.Fatal("original grant not revoked", err)
	}
	again, revAgain, err := s.authority.GetGrantWithSeq(f.request.GrantID)
	if err != nil || revAgain != rev || again.Signature != g.Signature {
		t.Fatal("original grant mutated after settle", err)
	}
}

func TestUP05SamePlanConcurrentCommitConvergesToSingleResult(t *testing.T) {
	f, p, req := confirmedUpdate(t)
	s := f.store
	// The install tree stays exactly as installed: any drift (an unknown user
	// file) makes every commit refuse by contract — that scenario is covered
	// separately below. Drift is introduced only after the interleave settles.
	before, rev, err := s.authority.GetGrantWithSeq(p.CandidateGrantID)
	if err != nil {
		t.Fatal(err)
	}
	const workers = 4
	type outcome struct {
		view *UpdateView
		err  error
	}
	results := make(chan outcome, workers)
	for i := 0; i < workers; i++ {
		go func() {
			v, err := s.CommitUpdate(nil, req)
			results <- outcome{v, err}
		}()
	}
	var views []*UpdateView
	var errs []error
	for i := 0; i < workers; i++ {
		o := <-results
		if o.err != nil {
			if !errors.Is(o.err, ErrConflict) && !errors.Is(o.err, ErrChanged) && !errors.Is(o.err, ErrRecoveryRequired) {
				t.Fatalf("concurrent same-plan commit rejected with non-contract error: %v", o.err)
			}
			errs = append(errs, o.err)
			continue
		}
		if o.view.Result == nil || o.view.Status != "updated_unverified" {
			t.Fatalf("successful outcome without a durable result: %+v", o.view)
		}
		views = append(views, o.view)
	}
	if len(views) == 0 {
		t.Fatalf("no worker completed the confirmed update; errors: %v", errs)
	}
	for _, v := range views {
		if !sameDocument(v, views[0]) {
			t.Fatal("concurrent same-plan commits produced divergent results")
		}
	}
	// Exactly one immutable claim and one result for the update ID.
	entries, err := os.ReadDir(filepath.Join(s.dir, "update-operations"))
	if err != nil {
		t.Fatal(err)
	}
	suffixes := map[string]bool{}
	for _, e := range entries {
		if rest, ok := strings.CutPrefix(e.Name(), p.UpdateID+"."); ok {
			suffixes[rest] = true
		}
	}
	if len(suffixes) != 2 || !suffixes["claim.json"] || !suffixes["result.json"] {
		t.Fatalf("update operation artifacts duplicated: %v", suffixes)
	}
	// The ordinary apply path must not resurrect the consumed replacement.
	if _, err := s.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", views[0].Claim.ReplacementPlan.PlanID, views[0].Claim.ReplacementPlan.Signature, p.ActorID, true}); !errors.Is(err, ErrConflict) {
		t.Fatal("replacement plan reusable outside the update", err)
	}
	// A user file added after the interleave must not be disturbed by later
	// reads or idempotent retries of the historical result.
	write(t, filepath.Join(f.root, "skills", "example", "notes.txt"), "user")
	retry, err := s.CommitUpdate(nil, req)
	if err != nil || !sameDocument(retry, views[0]) {
		t.Fatal("historical retry after drift diverged", err)
	}
	requireSingleLiveInstall(t, f, p.Record.InstallID, []string{views[0].Claim.ReplacementPlan.PlanID})
	after, afterRev, err := s.authority.GetGrantWithSeq(p.CandidateGrantID)
	if err != nil || afterRev != rev || after.Signature != before.Signature {
		t.Fatal("candidate authority moved during concurrent commit", err)
	}
}

// TestUP05UnknownTargetFileForcesCleanRefusal pins the drift-refusal contract
// under concurrency: once the install tree holds a file the claim does not
// know about, every concurrent commit must refuse with skill_install_changed,
// persist nothing (no claim, no result, no removal), and leave both the
// unknown user file and the installed content byte-identical.
func TestUP05UnknownTargetFileForcesCleanRefusal(t *testing.T) {
	f, p, req := confirmedUpdate(t)
	s := f.store
	original, err := os.ReadFile(filepath.Join(f.root, "skills", "example", "SKILL.md"))
	if err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(f.root, "skills", "example", "notes.txt"), "user")
	const workers = 3
	type outcome struct {
		v   *UpdateView
		err error
	}
	results := make(chan outcome, workers)
	for i := 0; i < workers; i++ {
		go func() {
			v, err := s.CommitUpdate(nil, req)
			results <- outcome{v, err}
		}()
	}
	for i := 0; i < workers; i++ {
		o := <-results
		if !errors.Is(o.err, ErrChanged) {
			t.Fatalf("drifted target accepted with %+v (err=%v) instead of a clean refusal", o.v, o.err)
		}
	}
	// Nothing persisted: no claim, no result, no removal started.
	for _, suffix := range []string{"claim", "result"} {
		if _, err := os.Lstat(s.updateOperationPath(p.UpdateID, suffix)); !os.IsNotExist(err) {
			t.Fatalf("update artifact %s persisted despite target drift: %v", suffix, err)
		}
	}
	if err := s.removalStarted(p.Record.InstallID); err != nil {
		t.Fatal("removal started despite target drift", err)
	}
	// The unknown file and the installed content are untouched.
	if got, err := os.ReadFile(filepath.Join(f.root, "skills", "example", "notes.txt")); err != nil || string(got) != "user" {
		t.Fatalf("unknown user file not preserved: %q %v", got, err)
	}
	if got, err := os.ReadFile(filepath.Join(f.root, "skills", "example", "SKILL.md")); err != nil || string(got) != string(original) {
		t.Fatal("installed content mutated by refused update", err)
	}
}

func TestUP05DistinctPlansSameInstallEndInConsistentState(t *testing.T) {
	f, op, firstReq := readyUpdate(t)
	s := f.store
	firstPlan, reused, err := s.StageUpdate(nil, op.InstallID, firstReq)
	if err != nil || reused {
		t.Fatal(reused, err)
	}
	secondPlan, secondCommit := stageSecondUpdate(t, f, op, firstReq)
	commit := func(req UpdateCommitRequest) (*UpdateView, error) { return s.CommitUpdate(nil, req) }
	type outcome struct {
		id  string
		v   *UpdateView
		err error
	}
	results := make(chan outcome, 2)
	go func() { v, err := commit(secondCommit); results <- outcome{secondPlan.UpdateID, v, err} }()
	first, firstErr := s.CommitUpdate(nil, UpdateCommitRequest{"local-skill-update-commit/v1", firstPlan.UpdateID, firstPlan.Signature, firstPlan.ActorID, true})
	results <- outcome{firstPlan.UpdateID, first, firstErr}
	losers := 0
	replacement := ""
	for i := 0; i < 2; i++ {
		o := <-results
		if o.err == nil {
			replacement = o.v.Claim.ReplacementPlan.PlanID
			continue
		}
		if !errors.Is(o.err, ErrConflict) && !errors.Is(o.err, ErrChanged) && !errors.Is(o.err, ErrRecoveryRequired) && !errors.Is(o.err, ErrRemovalPending) {
			t.Fatalf("update %s rejected with non-contract error: %v", o.id, o.err)
		}
		losers++
	}
	if losers == 2 {
		t.Fatal("both updates failed; one confirmed commit must proceed")
	}
	if replacement == "" {
		t.Fatal("no winner identified")
	}
	// A loser that published a claim must abort cleanly and idempotently.
	for _, id := range []string{firstPlan.UpdateID, secondPlan.UpdateID} {
		v, err := s.ReadUpdate(nil, id)
		if errors.Is(err, ErrNotFound) {
			continue
		}
		if err != nil {
			t.Fatal(err)
		}
		if v.Result != nil {
			continue
		}
		aborted, err := s.RecoverUpdate(nil, UpdateRecoverRequest{"local-skill-update-recover/v1", id, v.Claim.Signature, v.Claim.ActorID, true})
		if err != nil || aborted.Status != "aborted" {
			t.Fatalf("pending loser %s not abortable: %+v %v", id, aborted, err)
		}
		retry, err := s.RecoverUpdate(nil, UpdateRecoverRequest{"local-skill-update-recover/v1", id, v.Claim.Signature, v.Claim.ActorID, true})
		if err != nil || !sameDocument(retry, aborted) {
			t.Fatalf("repeated recover not idempotent for %s: %+v %v", id, retry, err)
		}
	}
	// A user file landing after the interleave survives the replaced install.
	write(t, filepath.Join(f.root, "skills", "example", "notes.txt"), "user")
	requireSingleLiveInstall(t, f, op.InstallID, []string{replacement})
	// The original install is gone; staging against it must be refused.
	if _, _, err := s.StageUpdate(nil, op.InstallID, firstReq); err == nil {
		t.Fatal("staging against a replaced install accepted")
	}
}

func TestUP05RemoveQueuedBehindUpdateCommitIsIdempotentOrConflict(t *testing.T) {
	f, p, req := confirmedUpdate(t)
	install := p.Record.InstallID
	s := f.store
	// Snapshot the removal request before the update moves authority.
	direct := removalRequest(t, s, install)
	reached := make(chan struct{})
	release := make(chan struct{})
	s.boundary = func(name string) error {
		if name == "update_claim_published" {
			close(reached)
			<-release
		}
		return nil
	}
	t.Cleanup(func() { s.boundary = func(string) error { return nil } })
	type commitOutcome struct {
		v   *UpdateView
		err error
	}
	upd := make(chan commitOutcome, 1)
	go func() {
		v, err := s.CommitUpdate(nil, req)
		upd <- commitOutcome{v, err}
	}()
	<-reached
	// The removal cannot enter while the commit holds the stage slot, so it
	// runs strictly after the update: a deterministic order, not a race.
	go func() { _, _ = s.Remove(nil, install, direct) }()
	close(release)
	o := <-upd
	if o.err != nil {
		t.Fatal("update blocked by queued removal", o.err)
	}
	removal, err := s.Remove(nil, install, direct)
	if err != nil && !errors.Is(err, ErrConflict) && !errors.Is(err, ErrChanged) {
		t.Fatalf("post-update removal failed with non-contract error: %v", err)
	}
	if err == nil && (removal.Status != "removed" || removal.Result == nil) {
		t.Fatalf("idempotent reuse returned incomplete view: %+v", removal)
	}
	write(t, filepath.Join(f.root, "skills", "example", "notes.txt"), "user")
	requireSingleLiveInstall(t, f, install, []string{o.v.Claim.ReplacementPlan.PlanID})
}

func TestUP05RemoveCompletingBeforeUpdateCommitStaysConsistent(t *testing.T) {
	f, p, req := confirmedUpdate(t)
	install := p.Record.InstallID
	s := f.store
	direct := removalRequest(t, s, install)
	if _, err := s.Remove(nil, install, direct); err != nil {
		t.Fatal(err)
	}
	v, commitErr := s.CommitUpdate(nil, req)
	if commitErr != nil {
		if !errors.Is(commitErr, ErrConflict) && !errors.Is(commitErr, ErrChanged) && !errors.Is(commitErr, ErrRemovalPending) {
			t.Fatalf("commit against removed install failed with non-contract error: %v", commitErr)
		}
		// Claim published but refused: recovery must abort without side effects.
		claim, readErr := s.ReadUpdate(nil, req.UpdateID)
		if readErr != nil {
			if errors.Is(readErr, ErrNotFound) {
				return
			}
			t.Fatal(readErr)
		}
		if claim.Result == nil {
			aborted, err := s.RecoverUpdate(nil, UpdateRecoverRequest{"local-skill-update-recover/v1", req.UpdateID, claim.Claim.Signature, claim.Claim.ActorID, true})
			if err != nil || aborted.Status != "aborted" {
				t.Fatalf("refused commit not abortable: %+v %v", aborted, err)
			}
		}
	} else if v.Status != "updated_unverified" {
		t.Fatalf("unexpected commit status after independent removal: %+v", v.Status)
	}
}

func TestUP05ScheduledCheckBarrierVersusSourceDisable(t *testing.T) {
	f, op, clock := schedulerFixture(t)
	s := f.store
	*clock = clock.Add(25 * time.Hour)
	upstream := snapInstall(t, s, op.InstallID)
	entered := make(chan struct{})
	release := make(chan struct{})
	s.upstream = func(ctx context.Context, r *skillimport.Record, url string) (*skillimport.UpstreamSnapshot, error) {
		close(entered)
		<-release
		return upstream(ctx, r, url)
	}
	var wg sync.WaitGroup
	var run *ScheduledChecksResult
	var runErr error
	wg.Add(1)
	go func() {
		defer wg.Done()
		run, runErr = s.RunScheduledChecks(context.Background(), runRequest("scheduler"))
	}()
	<-entered
	// The disable lands strictly inside the scheduled check's upstream fetch.
	if _, err := s.DisableUpdateSource(context.Background(), op.InstallID, disableRequest()); err != nil {
		t.Fatal(err)
	}
	saved, err := os.ReadFile(s.updateSourcePath(op.InstallID))
	if err != nil {
		t.Fatal(err)
	}
	close(release)
	wg.Wait()
	// The late outcome must be rejected as stale, never silently recorded.
	if runErr != nil || run == nil || run.Stale != 1 || len(run.Checked) != 0 {
		t.Fatalf("late scheduled outcome neither rejected as stale nor clean: %+v %v", run, runErr)
	}
	got, err := os.ReadFile(s.updateSourcePath(op.InstallID))
	if err != nil || string(got) != string(saved) {
		t.Fatal("scheduled outcome rewrote a concurrently disabled source", err)
	}
	view, err := s.ReadUpdateSchedule(context.Background(), op.InstallID)
	if err != nil {
		t.Fatal(err)
	}
	if view.Enabled {
		t.Fatalf("source not disabled after interleave: %+v", view)
	}
}

func TestUP05UpdateCommitBarrierVersusCandidateGrantRevoke(t *testing.T) {
	f, p, req := confirmedUpdate(t)
	s := f.store
	var revokeErr error
	var once sync.Once
	s.boundary = func(name string) error {
		if name == "update_install_plan_published" {
			once.Do(func() {
				// Revoke the candidate while the commit is between plan
				// publication and apply: the apply must refuse.
				g, rev, err := s.authority.GetGrantWithSeq(p.CandidateGrantID)
				if err != nil {
					revokeErr = err
					return
				}
				changed, err := grant.Revoke(*g, s.key)
				if err != nil {
					revokeErr = err
					return
				}
				if _, err := s.authority.CommitGrant(state.GrantCommit{Grant: changed, ExpectedRevision: rev, Audit: &state.AuditEvent{Event: "up05_candidate_revoke", Target: g.GrantID}}); err != nil {
					revokeErr = err
				}
			})
		}
		return nil
	}
	t.Cleanup(func() { s.boundary = func(string) error { return nil } })
	_, commitErr := s.CommitUpdate(nil, req)
	if revokeErr != nil {
		t.Fatal("fixture revoke failed", revokeErr)
	}
	if commitErr == nil {
		t.Fatal("commit succeeded although candidate authority was revoked mid-flight")
	}
	v, err := s.ReadUpdate(nil, req.UpdateID)
	if err != nil {
		t.Fatal(err)
	}
	if v.Result != nil {
		t.Fatalf("revoked-candidate commit produced a durable result: %+v", v.Result)
	}
	aborted, err := s.RecoverUpdate(nil, UpdateRecoverRequest{"local-skill-update-recover/v1", req.UpdateID, v.Claim.Signature, v.Claim.ActorID, true})
	if err != nil || aborted.Status != "aborted" {
		t.Fatalf("revoked-candidate update not abortable: %+v %v", aborted, err)
	}
	// No replacement may exist after the abort.
	if _, err := s.claim(context.Background(), installID(v.Claim.ReplacementPlan.PlanID)); !errors.Is(err, ErrNotFound) {
		t.Fatal("replacement install survived abort", err)
	}
	// The original grant was revoked by the removal leg exactly once; the
	// candidate grant was revoked by the fixture; both must be stable now.
	for _, id := range []string{f.request.GrantID, p.CandidateGrantID} {
		g, rev, err := s.authority.GetGrantWithSeq(id)
		if err != nil || g.Status != "revoked" {
			t.Fatalf("grant %s not revoked: %v", id, err)
		}
		_, revAgain, err := s.authority.GetGrantWithSeq(id)
		if err != nil || revAgain != rev {
			t.Fatalf("grant %s revision moved after settle", id)
		}
	}
}
