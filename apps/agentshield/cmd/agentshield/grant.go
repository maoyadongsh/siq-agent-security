package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func cmdGrant(args []string) error {
	if len(args) < 1 {
		return fmt.Errorf("grant: usage: agentshield grant <admission_id> --platform P --subject ID\n       agentshield grant approve|deploy|reject|revoke <grant_id> [--approve-as ACTOR]")
	}
	dir, err := stateDir()
	if err != nil {
		return err
	}
	st, err := state.Open(dir)
	if err != nil {
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
	case "approve", "deploy", "reject", "revoke":
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
	if existing, err := st.GetGrant(res.Grant.GrantID); err == nil && grant.IsLiveStatus(existing.Status) {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		return enc.Encode(map[string]any{
			"grant":  existing,
			"reused": true,
			"note":   "live grant " + existing.GrantID + " status=" + existing.Status + " was not replaced; approve only if still pending",
		})
	}
	if err := st.PutGrant(res.Grant); err != nil {
		return err
	}
	_ = st.PutDesiredPolicy(res.DesiredPolicy)
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(map[string]any{
		"grant":          res.Grant,
		"desired_policy": res.DesiredPolicy,
		"note":           "model must not approve; a human runs: agentshield grant approve " + res.Grant.GrantID + " --approve-as <actor>",
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
	if err := fs.Parse(flagArgs); err != nil {
		return err
	}
	if fs.NArg() != 0 {
		return fmt.Errorf("grant %s: unexpected extra args %v", verb, fs.Args())
	}
	g, err := st.GetGrant(id)
	if err != nil {
		return fmt.Errorf("grant: %w", err)
	}
	now := time.Now().UTC().Format(time.RFC3339)
	var out grant.Grant
	switch verb {
	case "approve":
		if *actor == "" {
			return fmt.Errorf("grant approve: --approve-as <human-actor-id> is required (ADR-003; the model must not approve)")
		}
		out, err = grant.Approve(*g, grant.Approval{ActorType: "human", ActorID: *actor, ApprovedAt: now, Channel: *channel}, key)
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
	if err := st.PutGrant(out); err != nil {
		return err
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(out)
}

// splitGrantIDAndFlags accepts both documented
// `grant approve <id> --approve-as NAME` and flag-first order. Go's flag.Parse
// otherwise stops at the first positional and never sees --approve-as.
func splitGrantIDAndFlags(args []string) (id string, flags []string, err error) {
	takesValue := map[string]bool{
		"--approve-as": true, "-approve-as": true,
		"--channel": true, "-channel": true,
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
