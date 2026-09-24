package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillcontext"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
	"siq-agent-security/apps/agentshield/internal/state"
)

// openSkillContexts builds the SEC store with every dependency re-reading live
// state. The install/import stores opened here are read-only views: the
// resolver fails closed because issuance and verification never write install
// state.
func openSkillContexts(st *state.Store, key *signing.Key, intents *intent.Store) (*skillcontext.Store, error) {
	pack, err := loadPack()
	if err != nil {
		return nil, err
	}
	imports, err := skillimport.Open(st.Dir, key, pack, Version)
	if err != nil {
		return nil, err
	}
	installs, err := skillinstall.Open(st, key, imports, func(ctx context.Context, id string) (skillinstall.Target, error) {
		if err := ctx.Err(); err != nil {
			return skillinstall.Target{}, err
		}
		home, err := os.UserHomeDir()
		if err != nil {
			return skillinstall.Target{}, skillinstall.ErrChanged
		}
		scope, _, scopeErr := st.LoadDiscoveryRoots()
		options := hermeshome.Options{
			Home:                    home,
			ProjectDirs:             scope.ProjectDirs,
			ProjectScopeUnavailable: scopeErr != nil,
			Override:                os.Getenv("HERMES_HOME"),
			LocalAppData:            os.Getenv("LOCALAPPDATA"),
		}
		root, err := hermeshome.Resolve(options, id)
		if err != nil || !root.Detected {
			return skillinstall.Target{}, skillinstall.ErrChanged
		}
		shown := filepath.ToSlash(root.Path)
		homeShown := strings.TrimSuffix(filepath.ToSlash(home), "/")
		if homeShown != "" && strings.HasPrefix(shown, homeShown+"/") {
			shown = "~" + strings.TrimPrefix(shown, homeShown)
		}
		return skillinstall.Target{InstanceID: root.ID, Platform: "hermes", Root: root.Path, Display: shown}, nil
	})
	if err != nil {
		return nil, err
	}
	// Reserved install grants resolve through the daemon's trusted content
	// verifier; the CLI must register the same check the server registers or
	// session bindings for installed skills can never resolve offline.
	st.SetRuntimeGrantCheck(func(g *grant.Grant) error {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		return installs.ValidateRuntimeGrant(ctx, g)
	})
	identities, err := runtimeidentity.Open(st.Dir, key, intents, func(string) (string, error) {
		return "", runtimeidentity.ErrUnavailable
	})
	if err != nil {
		return nil, err
	}
	return skillcontext.Open(st.Dir, skillcontext.Deps{
		Key: key,
		ReadGrant: func(grantID string) (*grant.Grant, error) {
			g := st.GrantByID(grantID)
			if g == nil {
				return nil, errors.New("skillcontext: grant not found")
			}
			return g, nil
		},
		ReadInstall: func(installID string) (*skillinstall.Record, error) {
			return installs.RecordByID(context.Background(), installID)
		},
		ReadInstance: identities.InspectByInstance,
		SessionBound: func(platform, agentID, sessionID, grantID string) (time.Time, error) {
			_, b, err := intents.ResolveBinding(platform, sessionID, agentID)
			if err != nil || b == nil || b.GrantRef == nil || b.GrantRef.GrantID != grantID {
				return time.Time{}, errors.New("skillcontext: session not bound to grant")
			}
			expires, err := time.Parse(time.RFC3339, b.ExpiresAt)
			if err != nil {
				return time.Time{}, errors.New("skillcontext: invalid session expiry")
			}
			return expires, nil
		},
	})
}

// cmdSkillContext manages skill execution contexts (N05/R01). Issuance is the
// operator-confirmed controlled start of a skill-bound session; the skill
// identity and authority digest are derived from stored records, never from
// flags.
func cmdSkillContext(args []string, out io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("skill-context: subcommand issue|revoke|get required")
	}
	dir, err := stateDir()
	if err != nil {
		return err
	}
	writer, err := state.AcquireWriter(dir)
	if err != nil {
		return fmt.Errorf("skill-context: %w", err)
	}
	defer func() { _ = writer.Release() }()
	key, err := signing.Load(dir)
	if err != nil {
		return err
	}
	st, err := state.Open(dir)
	if err != nil {
		return err
	}
	if _, err := st.RecoverGrantCommits(writer); err != nil {
		return err
	}
	intents, err := st.IntentAuthority(key)
	if err != nil {
		return err
	}
	contexts, err := openSkillContexts(st, key, intents)
	if err != nil {
		return err
	}
	switch args[0] {
	case "issue":
		fs := flag.NewFlagSet("skill-context issue", flag.ContinueOnError)
		instance := fs.String("instance", "", "managed instance id (hi-...)")
		session := fs.String("session", "", "enrolled session id")
		task := fs.String("task", "", "host task id (controlled_task evidence; empty = controlled_session)")
		installID := fs.String("install-id", "", "signed install record id")
		ttl := fs.Duration("ttl", time.Hour, "context lifetime (max 24h)")
		actor := fs.String("actor", "local-cli", "operator id recorded in audit")
		confirm := fs.Bool("confirm", false, "confirm issuing the context")
		if err := fs.Parse(args[1:]); err != nil {
			return err
		}
		if !*confirm {
			return fmt.Errorf("skill-context issue: --confirm required")
		}
		request := skillcontext.ManagementIssueRequest{
			SchemaVersion: skillcontext.IssueRequestSchema, InstanceID: *instance, SessionID: *session,
			TaskID: *task, InstallID: *installID, TTLSeconds: int(*ttl / time.Second), ActorID: *actor, ConfirmIssue: true,
		}
		if !request.Valid() || time.Duration(request.TTLSeconds)*time.Second != *ttl {
			return fmt.Errorf("skill-context issue: invalid request")
		}
		scope := skillcontext.EvidenceSession
		if *task != "" {
			scope = skillcontext.EvidenceTask
		}
		if err := st.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339Nano), Event: "skill_context_issue_authorized", ActorID: *actor, Target: *installID, Note: "scope=" + scope}); err != nil {
			return fmt.Errorf("skill-context issue: audit: %w", err)
		}
		c, err := contexts.Issue(skillcontext.IssueRequest{
			InstanceID: *instance, SessionID: *session, TaskID: *task, InstallID: *installID, TTL: *ttl,
		})
		if err != nil {
			return err
		}
		return json.NewEncoder(out).Encode(map[string]any{
			"context_id": c.ContextID, "subject": c.Subject, "skill": c.Skill,
			"evidence_level": c.EvidenceLevel, "issued_at": c.IssuedAt, "expires_at": c.ExpiresAt,
			"grant_id": c.Authority.GrantID,
		})
	case "revoke":
		fs := flag.NewFlagSet("skill-context revoke", flag.ContinueOnError)
		contextID := fs.String("context-id", "", "sec-... context to revoke")
		expected := fs.String("expected-signature", "", "signature of the inspected SEC (empty reads it under the CLI writer lock)")
		actor := fs.String("actor", "local-cli", "operator id recorded in audit")
		confirm := fs.Bool("confirm", false, "confirm revocation")
		if err := fs.Parse(args[1:]); err != nil {
			return err
		}
		if !*confirm {
			return fmt.Errorf("skill-context revoke: --confirm required")
		}
		c, err := contexts.Get(*contextID)
		if err != nil {
			return err
		}
		if *expected == "" {
			*expected = c.Signature
		}
		request := skillcontext.ManagementRevokeRequest{SchemaVersion: skillcontext.RevokeRequestSchema, ExpectedContextSignature: *expected, ActorID: *actor, ConfirmRevoke: true}
		if !request.Valid() {
			return fmt.Errorf("skill-context revoke: invalid request")
		}
		if err := st.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339Nano), Event: "skill_context_revoke_authorized", ActorID: *actor, Target: *contextID}); err != nil {
			return fmt.Errorf("skill-context revoke: audit: %w", err)
		}
		r, err := contexts.RevokeExpected(*contextID, *expected)
		if err != nil {
			return err
		}
		return json.NewEncoder(out).Encode(map[string]any{"context_id": r.ContextID, "revoked_at": r.RevokedAt})
	case "get":
		fs := flag.NewFlagSet("skill-context get", flag.ContinueOnError)
		contextID := fs.String("context-id", "", "sec-... context to show")
		if err := fs.Parse(args[1:]); err != nil {
			return err
		}
		c, err := contexts.Get(*contextID)
		if err != nil {
			return err
		}
		return json.NewEncoder(out).Encode(map[string]any{
			"context_id": c.ContextID, "subject": c.Subject, "skill": c.Skill,
			"evidence_level": c.EvidenceLevel, "issued_at": c.IssuedAt, "expires_at": c.ExpiresAt,
			"grant_id": c.Authority.GrantID, "grant_digest": c.Authority.GrantDigest,
			"install_id": c.Install.InstallID,
			"signature":  c.Signature,
		})
	default:
		return fmt.Errorf("skill-context: unknown subcommand %q", args[0])
	}
}
