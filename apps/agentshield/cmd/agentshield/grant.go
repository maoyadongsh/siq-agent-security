package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func cmdGrant(args []string) error {
	if len(args) < 1 {
		return fmt.Errorf("grant: usage: %s grant <admission_id> --platform P --subject ID\n       %s grant challenge|approve|deploy|reject|revoke <grant_id> [--approve-as ACTOR] [--challenge-id ID --nonce HEX]", product.Name, product.Name)
	}
	dir, err := stateDir()
	if err != nil {
		return err
	}
	if held, pid, err := state.WriterHeld(dir); err != nil {
		return err
	} else if held {
		return fmt.Errorf("grant: serve holds write lock (pid %d); use the local console or authenticated HTTP admin session — offline CLI must not bypass the single writer", pid)
	}
	writer, err := state.AcquireWriter(dir)
	if err != nil {
		return fmt.Errorf("grant: %w", err)
	}
	defer func() { _ = writer.Release() }()

	st, err := state.Open(dir)
	if err != nil {
		return err
	}
	if _, err := st.RecoverGrantCommits(writer); err != nil {
		return err
	}
	key, err := loadKey()
	if err != nil {
		return err
	}
	cfg, err := st.LoadConfig()
	if err != nil {
		return err
	}

	verb := args[0]
	switch verb {
	case "approve", "deploy", "reject", "revoke", "challenge":
		return cmdGrantAction(st, key, verb, args[1:])
	}

	fs := flag.NewFlagSet("grant", flag.ContinueOnError)
	platform := fs.String("platform", "", "openclaw|hermes|codebuddy|trae")
	subject := fs.String("subject", "", "agent instance id (grant subject)")
	subjectType := fs.String("subject-type", "agent_instance", "subject type")
	redact := fs.Bool("redact-secrets", true, "permit redact action on secret literals")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if *platform == "" || *subject == "" {
		return fmt.Errorf("grant: --platform and --subject are required")
	}
	adm, err := st.GetAdmission(verb)
	if err != nil {
		return fmt.Errorf("grant: admission %s: %w", verb, err)
	}
	res, err := grant.Build(*adm, grant.Options{
		Subject: grant.Subject{Type: *subjectType, ID: *subject}, Platform: *platform,
		EnforcementMode: cfg.EnforcementMode, Key: key, RedactSecrets: *redact,
	})
	if err != nil {
		return err
	}
	if existing, seq, err := st.GetGrantWithSeq(res.Grant.GrantID); err == nil && grant.IsLiveStatus(existing.Status) {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		return enc.Encode(map[string]any{
			"grant":          existing,
			"reused":         true,
			"state_revision": seq,
			"note":           "live grant " + existing.GrantID + " status=" + existing.Status + " was not replaced; approve only if still pending",
		})
	}
	expected, _, err := st.LatestSeq("grants", res.Grant.GrantID)
	if err != nil {
		return err
	}
	seq, err := st.CommitGrant(state.GrantCommit{
		Grant:            res.Grant,
		ExpectedRevision: expected,
		DesiredPolicy:    res.DesiredPolicy,
		Audit: &state.AuditEvent{
			At: time.Now().UTC().Format(time.RFC3339), Event: "grant_create", Target: res.Grant.GrantID,
		},
	})
	if err != nil {
		return err
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(map[string]any{
		"grant":          res.Grant,
		"desired_policy": res.DesiredPolicy,
		"state_revision": seq,
		"note":           "model must not approve; a human runs: " + product.Name + " grant challenge " + res.Grant.GrantID + " then " + product.Name + " grant approve " + res.Grant.GrantID + " --approve-as <actor> --challenge-id <id> --nonce <nonce>",
	})
}

func cmdGrantAction(st *state.Store, key *signing.Key, verb string, args []string) error {
	id, flagArgs, err := splitGrantIDAndFlags(args)
	if err != nil {
		return fmt.Errorf("grant %s: %w", verb, err)
	}
	fs := flag.NewFlagSet("grant-"+verb, flag.ContinueOnError)
	actor := fs.String("approve-as", "", "human actor id (required for approve)")
	channel := fs.String("channel", "cli", "approval channel recorded on the grant")
	challengeID := fs.String("challenge-id", "", "single-use approval challenge id (from grant challenge)")
	nonce := fs.String("nonce", "", "challenge nonce")
	if err := fs.Parse(flagArgs); err != nil {
		return err
	}
	if fs.NArg() != 0 {
		return fmt.Errorf("grant %s: unexpected extra args %v", verb, fs.Args())
	}
	g, seq, err := st.GetGrantWithSeq(id)
	if err != nil {
		return fmt.Errorf("grant: %w", err)
	}
	now := time.Now().UTC()
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")

	if verb == "challenge" {
		ch, err := grant.IssueChallenge(*g, seq, now)
		if err != nil {
			return err
		}
		if err := st.PutChallenge(*ch); err != nil {
			return err
		}
		return enc.Encode(map[string]any{
			"challenge":      ch,
			"state_revision": seq,
			"note":           "desktop-same-uid: this challenge is not an OS isolation boundary; use grant approve --challenge-id --nonce next",
		})
	}

	var out grant.Grant
	switch verb {
	case "approve":
		if *actor == "" {
			return fmt.Errorf("grant approve: --approve-as <human-actor-id> is required (ADR-003; the model must not approve)")
		}
		if *challengeID == "" || *nonce == "" {
			return fmt.Errorf("grant approve: --challenge-id and --nonce are required (run: %s grant challenge %s)", product.Name, id)
		}
		ch, chSeq, err := st.GetChallengeWithSeq(*challengeID)
		if err != nil {
			return fmt.Errorf("grant approve: unknown challenge: %w", err)
		}
		if err := grant.ValidateChallenge(*ch, *g, seq, *nonce, now); err != nil {
			return err
		}
		consumed := grant.MarkConsumed(*ch, now)
		if _, err := st.PutChallengeCAS(consumed, chSeq); err != nil {
			return err
		}
		out, err = grant.Approve(*g, grant.Approval{ActorType: "human", ActorID: *actor, ApprovedAt: now.Format(time.RFC3339), Channel: *channel}, key)
	case "deploy":
		out, err = grant.MarkDeployed(*g, key)
	case "reject":
		out, err = grant.Reject(*g, key)
	case "revoke":
		out, err = grant.Revoke(*g, key)
	}
	if err != nil {
		return err
	}
	auditEv := state.AuditEvent{
		At: now.Format(time.RFC3339), Event: "grant_" + verb, ActorID: *actor, Target: out.GrantID,
	}
	newSeq, err := st.CommitGrant(state.GrantCommit{
		Grant:            out,
		ExpectedRevision: seq,
		Audit:            &auditEv,
	})
	if err != nil {
		var conflict *state.RevisionConflictError
		if errors.As(err, &conflict) {
			return fmt.Errorf("grant %s: %w", verb, conflict)
		}
		return err
	}
	return enc.Encode(map[string]any{"grant": out, "state_revision": newSeq})
}

// splitGrantIDAndFlags accepts both documented
// `grant approve <id> --approve-as NAME` and flag-first order. Go's flag.Parse
// otherwise stops at the first positional and never sees --approve-as.
func splitGrantIDAndFlags(args []string) (id string, flags []string, err error) {
	takesValue := map[string]bool{
		"--approve-as": true, "-approve-as": true,
		"--channel": true, "-channel": true,
		"--challenge-id": true, "-challenge-id": true,
		"--nonce": true, "-nonce": true,
	}
	for i := 0; i < len(args); i++ {
		a := args[i]
		if strings.HasPrefix(a, "-") {
			flags = append(flags, a)
			if takesValue[a] && i+1 < len(args) && !strings.HasPrefix(args[i+1], "-") {
				flags = append(flags, args[i+1])
				i++
			}
			continue
		}
		if id != "" {
			return "", nil, fmt.Errorf("unexpected extra arg %q", a)
		}
		id = a
	}
	if id == "" {
		return "", nil, fmt.Errorf("grant id required")
	}
	return id, flags, nil
}
