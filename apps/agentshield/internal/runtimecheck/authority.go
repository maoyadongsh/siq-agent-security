package runtimecheck

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/state"
)

type probes struct{ dir, first, last, forbidden, proof string }

// prepare runs under the manager lock before starting the host. All authority
// uses the existing signed stores; the model never approves or holds admin keys.
func (m *Manager) prepare(r *run) (probes, error) {
	p := probes{dir: m.materials(r.record.Result.ID)}
	if err := os.Mkdir(p.dir, 0700); err != nil {
		return p, errors.New("runtime_check_materials_failed")
	}
	allowed := filepath.Join(p.dir, "allowed")
	skill := filepath.Join(p.dir, "template")
	for _, dir := range []string{allowed, skill} {
		if err := os.Mkdir(dir, 0700); err != nil {
			return p, errors.New("runtime_check_materials_failed")
		}
	}
	proof, err := randomHex(16)
	if err != nil {
		return p, err
	}
	p.proof = "SIQ runtime check " + proof
	p.first, p.last, p.forbidden = filepath.Join(allowed, "first.txt"), filepath.Join(allowed, "last.txt"), filepath.Join(p.dir, "must-not-exist.txt")
	for _, file := range []string{p.first, p.last} {
		if err := os.WriteFile(file, []byte(p.proof+"\n"), 0600); err != nil {
			return p, errors.New("runtime_check_materials_failed")
		}
	}
	content := "---\nname: " + r.record.Result.ID + "\ndescription: Read SIQ generated test files.\nallowed-tools: read_file\n---\nRead only the generated test files.\n"
	if err := os.WriteFile(filepath.Join(skill, "SKILL.md"), []byte(content), 0600); err != nil {
		return p, errors.New("runtime_check_materials_failed")
	}
	adm, err := admission.Admit(skill, admission.Options{Key: m.o.Key, Pack: m.o.Pack, Version: "runtime-check/v1"})
	if err != nil || adm.Admission.Verdict == "quarantine" {
		return p, errors.New("runtime_check_template_rejected")
	}
	if err = m.o.Store.PutAdmission(adm); err != nil {
		return p, errors.New("runtime_check_authority_persist_failed")
	}
	deadline, err := time.Parse(time.RFC3339Nano, r.record.Result.ExpiresAt)
	if err != nil {
		return p, errors.New("runtime_check_deadline_invalid")
	}
	built, err := grant.Build(adm.Admission, grant.Options{Subject: grant.Subject{Type: "agent_instance", ID: agentID(r.record.Result.ID)}, Platform: "hermes", Key: m.o.Key, ExpiresAt: &deadline})
	if err != nil {
		return p, errors.New("runtime_check_grant_failed")
	}
	r.record.GrantID = built.Grant.GrantID
	if err = m.persist(&r.record); err != nil {
		return p, err
	}
	seq := -1
	commit := func(g grant.Grant, policy grant.DesiredPolicy, event string) error {
		var err error
		seq, err = m.o.Store.CommitGrant(state.GrantCommit{Grant: g, DesiredPolicy: policy, ExpectedRevision: seq, Audit: &state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339Nano), Event: event, ActorID: r.record.Actor, Target: g.GrantID}})
		return err
	}
	if err = commit(built.Grant, built.DesiredPolicy, "runtime_check_grant_create"); err != nil {
		return p, errors.New("runtime_check_authority_persist_failed")
	}
	g, policy, err := grant.PatchDesired(built.Grant, grant.DesiredPatch{HasFilesystem: true, Filesystem: &grant.FilesystemPatch{ReadOnly: []string{allowed}, ReadWrite: []string{}}}, m.o.Key)
	if err != nil || commit(g, policy, "runtime_check_grant_scope") != nil {
		return p, errors.New("runtime_check_grant_failed")
	}
	// The user confirmed this immutable preview's fixed scope. Preserve the
	// normal challenge digest validation before invoking the Grant state machine.
	challenge, err := grant.IssueChallenge(g, seq, time.Now())
	if err != nil || grant.ValidateChallenge(*challenge, g, seq, challenge.Nonce, time.Now()) != nil {
		return p, errors.New("runtime_check_approval_failed")
	}
	approval := grant.Approval{ActorType: "human", ActorID: r.record.Actor, ApprovedAt: time.Now().UTC().Format(time.RFC3339Nano), Channel: "console"}
	g, err = grant.Approve(g, approval, m.o.Key)
	if err != nil || commit(g, nil, "runtime_check_grant_approve") != nil {
		return p, errors.New("runtime_check_approval_failed")
	}
	g, err = grant.MarkDeployed(g, m.o.Key)
	if err != nil || commit(g, nil, "runtime_check_grant_deploy") != nil {
		return p, errors.New("runtime_check_authority_persist_failed")
	}
	now := time.Now().UTC().Add(-time.Second).Format(time.RFC3339Nano)
	c, err := m.o.Intents.Issue(intent.Contract{SchemaVersion: "intent/v2", IntentID: r.record.IntentID, TaskID: "rct-" + strings.TrimPrefix(r.record.Result.ID, "rc-"), Principal: intent.Principal{Type: "user", ID: r.record.Actor}, Agent: intent.Agent{ID: agentID(r.record.Result.ID), Platform: "hermes"}, Purpose: "Read SIQ generated runtime check files", AllowedTools: []string{"read_file"}, AllowedEffects: []string{"file.read"}, ResourceConstraints: []intent.ResourceConstraint{{Domain: "filesystem", Operator: "prefix", Value: allowed}}, ParameterConstraints: []intent.ParameterConstraint{}, IssuedAt: now, ValidFrom: now, ExpiresAt: deadline.Format(time.RFC3339Nano), Authority: intent.Authority{Issuer: "local-admin", Revision: "runtime-check/v1", EvidenceIDs: []string{}}})
	if err != nil {
		return p, errors.New("runtime_check_intent_failed")
	}
	r.record.IntentDigest = c.Digest
	if err = m.persist(&r.record); err != nil {
		return p, err
	}
	return p, nil
}

// cleanup is idempotent and always attempts every independent withdrawal.
func (m *Manager) cleanup(r *record) {
	ok := true
	if r.IntentID != "" {
		c, err := m.o.Intents.Get(r.IntentID)
		if err == nil {
			if _, err = m.o.Intents.RevokeIntent(c.IntentID, c.Digest); err != nil {
				ok = false
			}
			if r.BindingID != "" {
				if _, err = m.o.Intents.RevokeBinding(r.BindingID, c.Digest); err != nil {
					ok = false
				}
			} else {
				// Bind may have committed just before a crash prevented the
				// journal from receiving its ID. Resolve only this owned Intent.
				bindings, e := m.o.Intents.ListBindings()
				if e != nil {
					ok = false
				} else {
					for _, binding := range bindings {
						if binding.IntentID == c.IntentID {
							if _, e = m.o.Intents.RevokeBinding(binding.BindingID, c.Digest); e != nil {
								ok = false
							}
						}
					}
				}
			}
		} else if !errors.Is(err, os.ErrNotExist) {
			ok = false
		}
	}
	if r.GrantID != "" {
		g, seq, err := m.o.Store.GetGrantWithSeq(r.GrantID)
		if err == nil && g.Status != "revoked" && g.Status != "rejected" {
			next, e := grant.Revoke(*g, m.o.Key)
			if e != nil {
				ok = false
			} else if _, e = m.o.Store.CommitGrant(state.GrantCommit{Grant: next, ExpectedRevision: seq, Audit: &state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339Nano), Event: "runtime_check_grant_revoke", ActorID: r.Actor, Target: g.GrantID}}); e != nil {
				ok = false
			}
		} else if err != nil && !errors.Is(err, os.ErrNotExist) {
			ok = false
		}
	}
	parent := filepath.Dir(m.materials(r.Result.ID))
	info, err := os.Lstat(parent)
	if !idPattern.MatchString(r.Result.ID) || err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		ok = false
	} else if err = os.RemoveAll(m.materials(r.Result.ID)); err != nil {
		ok = false
	}
	r.Result.Cleanup = "complete"
	if !ok {
		r.Result.Cleanup = "failed"
	}
}
