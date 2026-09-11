package runtimeidentity

import (
	"encoding/json"
	"errors"
	"os"
	"reflect"
	"sort"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
)

type EnrollRequest struct {
	SchemaVersion string `json:"schema_version"`
	SessionID     string `json:"session_id"`
}

const permissionPurpose = "按用户确认的实例权限运行（任务目的未单独确认）"

func sessionNames(r Record, session string) (string, string) {
	b, _ := json.Marshal([]string{r.IdentityID, session})
	suffix := hash(b)
	return "int-ri-" + suffix, "task-ri-" + suffix
}

func permissionEnvelope(r Record, session string, g *grant.Grant, at time.Time) intent.Contract {
	id, task := sessionNames(r, session)
	allow, approval := grant.RuntimeToolSets(g)
	for tool := range approval {
		allow[tool] = true
	}
	tools := make([]string, 0, len(allow))
	for tool := range allow {
		tools = append(tools, tool)
	}
	sort.Strings(tools)
	expires := at.Add(time.Duration(r.SessionTTLSeconds) * time.Second)
	if g.ExpiresAt != nil {
		end, e := time.Parse(time.RFC3339Nano, *g.ExpiresAt)
		if e == nil && end.Before(expires) {
			expires = end
		}
	}
	return intent.Contract{
		SchemaVersion: "intent/v2", IntentID: id, TaskID: task,
		Principal: intent.Principal{Type: "user", ID: r.ActorID}, Agent: intent.Agent{ID: r.AgentID, Platform: r.Platform},
		Purpose: permissionPurpose, AllowedTools: tools,
		// This envelope selects instance permissions, not inferred task intent.
		// Grant still checks each resource and condition; unknown effects remain denied.
		AllowedEffects:      []string{"tool.invoke", "file.read", "file.write", "file.delete", "network.request", "process.exec", "message.send", "database.read", "database.write", "secret.read"},
		ResourceConstraints: []intent.ResourceConstraint{}, ParameterConstraints: []intent.ParameterConstraint{},
		IssuedAt: at.UTC().Format(time.RFC3339Nano), ValidFrom: at.UTC().Format(time.RFC3339Nano), ExpiresAt: expires.UTC().Format(time.RFC3339Nano),
		Authority: intent.Authority{Issuer: "local-runtime-identity", Revision: recordDigest(r), EvidenceIDs: []string{}},
	}
}

func sameEnvelope(c intent.Contract, want intent.Contract) bool {
	// Get verified the signature already. Only these server-derived cryptographic
	// output fields are excluded from the retry comparison.
	c.SigningSchema = ""
	c.Digest = ""
	c.Signature = ""
	return reflect.DeepEqual(c, want)
}

// Enroll binds the native session to this identity's exact permission reference.
// A retry never extends its deadline, resurrects a revoked session, or switches
// an already-bound session to a new identity. No prompt text is accepted.
func (s *Store) Enroll(token, session string) (intent.Binding, error) {
	writeMu.Lock()
	defer writeMu.Unlock()
	if !textValid(session, 256) {
		return intent.Binding{}, ErrInvalid
	}
	r, err := s.authenticate(token)
	if err != nil {
		return intent.Binding{}, err
	}
	g, err := s.intents.GrantForReference(r.GrantRef, r.Platform, r.AgentID)
	if err != nil {
		return intent.Binding{}, ErrUnavailable
	}
	c, b, err := s.intents.ResolveBinding(r.Platform, session, r.AgentID)
	if err != nil {
		return intent.Binding{}, ErrUnavailable
	}
	if b != nil {
		if !bindingMatches(r, session, c, b) {
			return intent.Binding{}, ErrConflict
		}
		return *b, nil
	}
	id, _ := sessionNames(r, session)
	existing, err := s.intents.Get(id)
	var envelope intent.Contract
	if errors.Is(err, os.ErrNotExist) {
		envelope = permissionEnvelope(r, session, g, time.Now())
		signed, e := s.intents.Issue(envelope)
		if e != nil {
			return intent.Binding{}, e
		}
		envelope = *signed
	} else if err != nil {
		return intent.Binding{}, ErrUnavailable
	} else {
		// Recover an issuance interrupted before binding, retaining its original time.
		at, e := time.Parse(time.RFC3339Nano, existing.IssuedAt)
		if e != nil || !sameEnvelope(existing, permissionEnvelope(r, session, g, at)) || existing.Active(time.Now()) != nil {
			return intent.Binding{}, ErrConflict
		}
		envelope = existing
	}
	return s.intents.BindWithReference(intent.Binding{Platform: r.Platform, AgentID: r.AgentID, SessionID: session, IntentID: envelope.IntentID}, r.GrantRef)
}
func bindingMatches(r Record, session string, c *intent.Contract, b *intent.Binding) bool {
	id, task := sessionNames(r, session)
	return c != nil && b != nil && c.IntentID == id && b.IntentID == id && c.TaskID == task && b.TaskID == task && c.Authority.Issuer == "local-runtime-identity" && c.Authority.Revision == recordDigest(r) && b.GrantRef != nil && *b.GrantRef == r.GrantRef
}

// AuthorizeSession is the required credential + session boundary for middleware.
// Authenticating the bearer alone must never authorize another session or agent.
func (s *Store) AuthorizeSession(token, platform, agent, session string) (intent.Binding, error) {
	writeMu.RLock()
	defer writeMu.RUnlock()
	if !textValid(session, 256) {
		return intent.Binding{}, ErrInvalid
	}
	r, err := s.authenticate(token)
	if err != nil || r.Platform != platform || r.AgentID != agent {
		return intent.Binding{}, ErrUnavailable
	}
	c, b, err := s.intents.ResolveBinding(platform, session, agent)
	if err != nil || !bindingMatches(r, session, c, b) {
		return intent.Binding{}, ErrUnavailable
	}
	return *b, nil
}
