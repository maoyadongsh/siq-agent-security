package adapterinstall

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/state"
)

type operationClaim struct {
	Schema   string `json:"schema"`
	ID       string `json:"id"`
	Digest   string `json:"digest"`
	Platform string `json:"platform"`
	Action   string `json:"action"`
	Record   Record `json:"record"`
}
type operationEnd struct {
	ID     string `json:"id"`
	Digest string `json:"digest"`
	State  string `json:"state"`
}

// Used only by isolated fault-injection tests; not configured by environment,
// HTTP input, plugin code or platform configuration.
var transactionBoundary = func(string) error { return nil }

func transactionPath(dir, id, suffix string) string {
	return filepath.Join(dir, "adapter-transactions", id+suffix)
}

func validPlanID(id string) bool {
	if len(id) != 35 || id[:3] != "ap-" {
		return false
	}
	_, err := hex.DecodeString(id[3:])
	return err == nil
}

func privateRead(path string, limit int64) ([]byte, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > limit || runtime.GOOS != "windows" && info.Mode().Perm()&0o077 != 0 {
		return nil, errors.New("adapter: private recovery file invalid")
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	raw, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err != nil || int64(len(raw)) > limit {
		return nil, errors.New("adapter: recovery read limit")
	}
	return raw, nil
}

func publishFile(path string, raw []byte, mode os.FileMode, replace bool) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".siq-adapter-pending-*")
	if err != nil {
		return err
	}
	tmp := f.Name()
	defer os.Remove(tmp)
	if err := f.Chmod(mode); err != nil {
		_ = f.Close()
		return err
	}
	if _, err := f.Write(raw); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	if replace {
		return os.Rename(tmp, path)
	}
	return os.Link(tmp, path)
}

func backupAEAD(dir string, create bool) (cipher.AEAD, error) {
	path := filepath.Join(dir, "adapter-backup.key")
	key, err := privateRead(path, 32)
	if os.IsNotExist(err) && create {
		key = make([]byte, 32)
		if _, err = rand.Read(key); err != nil {
			return nil, err
		}
		if err = publishFile(path, key, 0o600, false); os.IsExist(err) {
			key, err = privateRead(path, 32)
		}
	}
	if err != nil || len(key) != 32 {
		return nil, errors.New("adapter: backup key unavailable")
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	return cipher.NewGCM(block)
}

func sealPlan(p *Plan) error {
	aead, err := backupAEAD(p.payload.Options.StateDir, true)
	if err != nil {
		return err
	}
	raw, err := json.Marshal(p.payload)
	if err != nil || len(raw) > 96<<20 {
		return errors.New("adapter: recovery material limit")
	}
	nonce := make([]byte, aead.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return err
	}
	sealed := aead.Seal(nonce, nonce, raw, []byte(p.payload.View.PlanID))
	return publishFile(transactionPath(p.payload.Options.StateDir, p.payload.View.PlanID, ".sealed"), sealed, 0o600, false)
}

func unsealPlan(dir string, claim operationClaim) (*Plan, error) {
	if !validPlanID(claim.ID) {
		return nil, errors.New("adapter: invalid recovery identity")
	}
	aead, err := backupAEAD(dir, false)
	if err != nil {
		return nil, err
	}
	sealed, err := privateRead(transactionPath(dir, claim.ID, ".sealed"), 97<<20)
	if err != nil || len(sealed) < aead.NonceSize() {
		return nil, errors.New("adapter: recovery material unavailable")
	}
	raw, err := aead.Open(nil, sealed[:aead.NonceSize()], sealed[aead.NonceSize():], []byte(claim.ID))
	if err != nil {
		return nil, errors.New("adapter: recovery authentication failed")
	}
	var payload planPayload
	if json.Unmarshal(raw, &payload) != nil || payload.Options.StateDir != dir || payload.View.PlanID != claim.ID || payload.View.Platform != claim.Platform || payload.View.Action != claim.Action || len(payload.Files) > 32 {
		return nil, errors.New("adapter: invalid recovery material")
	}
	p := &Plan{payload: payload}
	digest, err := p.digest()
	if err != nil || digest != claim.Digest || digest != p.payload.View.PlanDigest {
		return nil, errors.New("adapter: recovery digest mismatch")
	}
	return p, nil
}

func endState(dir string, claim operationClaim) (string, error) {
	if !validPlanID(claim.ID) {
		return "", errors.New("adapter: invalid operation identity")
	}
	if !validPlanID(claim.ID) {
		return "", errors.New("adapter: invalid operation identity")
	}
	raw, err := privateRead(transactionPath(dir, claim.ID, ".end.json"), 4096)
	if os.IsNotExist(err) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	var end operationEnd
	if json.Unmarshal(raw, &end) != nil || end.ID != claim.ID || end.Digest != claim.Digest || end.State != "committed" && end.State != "rolled_back" {
		return "", errors.New("adapter: invalid operation result")
	}
	return end.State, nil
}

func finishOperation(dir string, claim operationClaim, status string) error {
	raw, _ := json.Marshal(operationEnd{ID: claim.ID, Digest: claim.Digest, State: status})
	return publishFile(transactionPath(dir, claim.ID, ".end.json"), raw, 0o600, false)
}

func latestManagedRecord(dir, platform string, namespace ...string) (*Record, bool, error) {
	key := platform
	if len(namespace) > 0 {
		key = namespace[0]
	}
	st := &state.Store{Dir: dir}
	rev, raw, err := st.LatestSeq("adapter-operations", key)
	if err != nil || rev < 0 {
		return nil, false, err
	}
	for ; rev >= 0; rev-- {
		if raw == nil {
			var err error
			raw, err = privateRead(filepath.Join(dir, "adapter-operations", fmt.Sprintf("%s.%d.json", key, rev)), 2<<20)
			if err != nil {
				return nil, true, err
			}
		}
		var claim operationClaim
		if json.Unmarshal(raw, &claim) != nil || claim.Schema != "adapter-operation/v1" || claim.Platform != platform {
			return nil, true, errors.New("adapter: invalid operation record")
		}
		status, err := endState(dir, claim)
		if err != nil {
			return nil, true, err
		}
		if status == "" {
			return nil, true, ErrRecoveryRequired
		}
		if status == "committed" {
			if claim.Action == "uninstall" {
				return nil, true, errNoInstallRecord
			}
			if claim.Action != "install" {
				return nil, true, errors.New("adapter: invalid recorded action")
			}
			plan, err := unsealPlan(dir, claim)
			if err != nil || operationKey(planOptions(plan)) != key {
				return nil, true, errors.New("adapter: authenticated ownership unavailable")
			}
			return &plan.payload.Record, true, nil
		}
		raw = nil
	}
	return nil, false, nil
}

func (p *Plan) verifyCurrent() error {
	expires, err := time.Parse(time.RFC3339, p.payload.View.ExpiresAt)
	if err != nil || !time.Now().Before(expires) {
		return errors.New("adapter: preview expired")
	}
	if digest, err := p.digest(); err != nil || digest != p.payload.View.PlanDigest {
		return errors.New("adapter: preview digest invalid")
	}
	if p.payload.NativeCLIDigest != "" {
		if digest, err := programDigest(p.payload.Options.NativeCLI); err != nil || digest != p.payload.NativeCLIDigest {
			return ErrPlanChanged
		}
	}
	if p.payload.BinaryDigest != "" {
		if digest, err := programDigest(p.payload.Options.Binary); err != nil || digest != p.payload.BinaryDigest {
			return ErrPlanChanged
		}
	}
	for path, before := range p.payload.Inputs {
		current, err := readImage(p.payload.Options.Home, path)
		if err != nil || !sameImage(current, before) {
			return ErrPlanChanged
		}
	}
	return nil
}

func writeImage(home, path string, before, after fileImage) error {
	current, err := readImage(home, path)
	if err != nil || !sameImage(current, before) {
		return ErrPlanChanged
	}
	if !after.Exists {
		if !before.Exists {
			return nil
		}
		return os.Remove(path)
	}
	return publishFile(path, after.Data, os.FileMode(after.Mode), before.Exists)
}

func rollback(p *Plan) error {
	conflict := false
	for i := len(p.payload.Files) - 1; i >= 0; i-- {
		op := p.payload.Files[i]
		current, err := readImage(p.payload.Options.Home, op.Path)
		if err != nil {
			conflict = true
			continue
		}
		if sameImage(current, op.Before) {
			continue
		}
		if !sameImage(current, op.After) {
			conflict = true
			continue
		}
		if err := writeImage(p.payload.Options.Home, op.Path, op.After, op.Before); err != nil {
			conflict = true
		}
	}
	if conflict {
		return ErrRecoveryRequired
	}
	return nil
}

func transactionResult(p *Plan, action string) *Result {
	paths := []string{}
	for _, op := range p.payload.Files {
		if !strings.HasSuffix(op.Path, originalSuffix) {
			paths = append(paths, op.Path)
		}
	}
	if action == "install" {
		for path := range p.payload.Record.Written {
			paths = appendUnique(paths, path)
		}
		sort.Strings(paths)
	}
	note := "configuration operation only; runtime verification remains required"
	if action == "uninstall" {
		note = "surgical: removed owned configuration; other settings preserved"
	}
	return &Result{Platform: p.payload.View.Platform, Action: action, Paths: paths, Record: &p.payload.Record, Note: note}
}

func Apply(p *Plan) (*Result, error) {
	if p != nil {
		if err := p.requireIdentityWithdrawal(); err != nil {
			return nil, err
		}
	}
	if err := validateTransactionStore(p.payload.Options.StateDir); err != nil {
		return nil, err
	}
	if p.payload.View.Platform == Trae {
		return &Result{Platform: Trae, Action: "skipped", Paths: []string{}, Note: "audit-only platform; no adapter hook installed"}, nil
	}
	st, err := state.Open(p.payload.Options.StateDir)
	if err != nil {
		return nil, err
	}
	guard, err := state.AcquireWriter(filepath.Join(st.Dir, "adapter-write"))
	if err != nil {
		return nil, err
	}
	defer guard.Release()
	claim := operationClaim{Schema: "adapter-operation/v1", ID: p.payload.View.PlanID, Digest: p.payload.View.PlanDigest, Platform: p.payload.View.Platform, Action: p.payload.View.Action, Record: p.payload.Record}
	if status, err := endState(st.Dir, claim); err != nil {
		return nil, err
	} else if status == "committed" {
		return transactionResult(p, claim.Action), nil
	} else if status != "" {
		return nil, errors.New("adapter: preview already rolled back")
	}
	if err := p.verifyCurrent(); err != nil {
		return nil, err
	}
	if _, _, err := latestManagedRecord(st.Dir, claim.Platform, operationKey(p.payload.Options)); err != nil && !errors.Is(err, errNoInstallRecord) {
		return nil, err
	}
	revision, _, err := st.LatestSeq("adapter-operations", operationKey(p.payload.Options))
	if err != nil || revision != p.payload.ExpectedRevision {
		return nil, ErrPlanChanged
	}
	if err := sealPlan(p); err != nil {
		return nil, err
	}
	if _, err := st.PutVersionedCAS("adapter-operations", operationKey(p.payload.Options), p.payload.ExpectedRevision, claim); err != nil {
		return nil, err
	}
	fail := func(cause error) (*Result, error) {
		res := transactionResult(p, "rolled_back")
		if err := rollback(p); err != nil {
			res.Action = "recovery_required"
			res.Recovery = &RecoveryPlan{Reason: "operation interrupted; changed files preserved", SuggestedActions: []string{"inspect the target configuration, then retry adapter recovery"}}
			return res, ErrRecoveryRequired
		}
		if err := finishOperation(st.Dir, claim, "rolled_back"); err != nil {
			return res, ErrRecoveryRequired
		}
		_ = st.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339), Event: "adapter_rolled_back", Target: claim.ID})
		return res, cause
	}
	if err := st.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339), Event: "adapter_started", ActorID: "local-admin", Target: claim.ID, Note: claim.Platform + ":" + claim.Action}); err != nil {
		return fail(errors.New("adapter: start audit unavailable"))
	}
	if err := transactionBoundary("prepared"); err != nil {
		return fail(err)
	}
	for i, op := range p.payload.Files {
		if err := writeImage(p.payload.Options.Home, op.Path, op.Before, op.After); err != nil {
			return fail(err)
		}
		if err := transactionBoundary(fmt.Sprintf("file:%d", i)); err != nil {
			return fail(err)
		}
	}
	// Read back all reviewed inputs before recording success, including no-op files.
	expected := make(map[string]fileImage, len(p.payload.Inputs))
	for path, before := range p.payload.Inputs {
		expected[path] = before
	}
	for _, op := range p.payload.Files {
		expected[op.Path] = op.After
	}
	for path, after := range expected {
		current, err := readImage(p.payload.Options.Home, path)
		if err != nil || !sameImage(current, after) {
			return fail(ErrPlanChanged)
		}
	}
	if err := st.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339), Event: "adapter_files_applied", ActorID: "local-admin", Target: claim.ID, Note: claim.Platform + ":" + claim.Action}); err != nil {
		return fail(errors.New("adapter: completion audit unavailable"))
	}
	if err := transactionBoundary("audited"); err != nil {
		return fail(err)
	}
	if err := finishOperation(st.Dir, claim, "committed"); err != nil {
		return fail(errors.New("adapter: completion marker unavailable"))
	}
	return transactionResult(p, claim.Action), nil
}

// Recover rolls back an unfinished operation only after acquiring the same
// cross-process guard as Apply. It never completes or reauthorizes an install.
func Recover(dir, platform string) (*Result, error) { return recoverOperation(dir, platform, platform) }

func recoverOperation(dir, platform, key string) (*Result, error) {
	if err := validateTransactionStore(dir); err != nil {
		return nil, err
	}
	if !known[platform] {
		return nil, errors.New("adapter: unknown platform")
	}
	guard, err := state.AcquireWriter(filepath.Join(dir, "adapter-write"))
	if err != nil {
		return nil, err
	}
	defer guard.Release()
	st := &state.Store{Dir: dir}
	revision, raw, err := st.LatestSeq("adapter-operations", key)
	if err != nil {
		return nil, err
	}
	if revision < 0 {
		return &Result{Platform: platform, Action: "no_recovery_needed", Paths: []string{}}, nil
	}
	var claim operationClaim
	if json.Unmarshal(raw, &claim) != nil || claim.Platform != platform || claim.Schema != "adapter-operation/v1" {
		return nil, errors.New("adapter: invalid recovery claim")
	}
	status, err := endState(dir, claim)
	if err != nil {
		return nil, err
	}
	if status != "" {
		return &Result{Platform: platform, Action: "no_recovery_needed", Paths: []string{}}, nil
	}
	p, err := unsealPlan(dir, claim)
	if err != nil {
		return nil, err
	}
	if err := st.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339), Event: "adapter_recovery_started", Target: claim.ID}); err != nil {
		return nil, errors.New("adapter: recovery audit unavailable")
	}
	if err := rollback(p); err != nil {
		return transactionResult(p, "recovery_required"), err
	}
	if err := st.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339), Event: "adapter_recovery_rolled_back", Target: claim.ID}); err != nil {
		return nil, errors.New("adapter: recovery audit unavailable")
	}
	if err := finishOperation(dir, claim, "rolled_back"); err != nil {
		return nil, err
	}
	return transactionResult(p, "rolled_back"), nil
}

func validateTransactionStore(dir string) error {
	if !filepath.IsAbs(dir) {
		return errors.New("adapter: absolute state directory required")
	}
	for _, name := range []string{"", "adapter-transactions", "adapter-operations", "adapter-write"} {
		info, err := os.Lstat(filepath.Join(dir, name))
		if os.IsNotExist(err) {
			continue
		}
		if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0 {
			return errors.New("adapter: private operation directory invalid")
		}
	}
	return nil
}

func planOptions(p *Plan) Options {
	if p == nil {
		return Options{}
	}
	return p.payload.Options
}
