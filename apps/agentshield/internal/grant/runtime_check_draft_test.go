package grant

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestRuntimeCheckDraftRequiresSignedBoundedTemplate(t *testing.T) {
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	pack, _ := rulepack.Builtin()
	id := "rc-" + strings.Repeat("a", 32)
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "SKILL.md"), []byte("---\nname: "+id+"\ndescription: Read SIQ generated test files.\nallowed-tools: read_file\n---\nRead only the generated test files.\n"), 0600); err != nil {
		t.Fatal(err)
	}
	adm, err := admission.Admit(root, admission.Options{Key: key, Pack: pack, Version: "runtime-check/v1"})
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	until := now.Add(120 * time.Second)
	opts := Options{Key: key, Now: now, ExpiresAt: &until, Subject: Subject{Type: "agent_instance", ID: "rca-" + strings.TrimPrefix(id, "rc-")}, Platform: "hermes"}
	g, err := BuildRuntimeCheckDraft(adm.Admission, opts, id)
	if err != nil || g.Grant.Skill != nil || g.Grant.GrantID != "grt-rc-"+strings.TrimPrefix(id, "rc-") || g.Grant.Status != "pending_approval" || !Verify(key.Public(), g.Grant) || !admission.Verify(key.Public(), adm.Admission) {
		t.Fatal("valid standalone draft failed", err)
	}
	for name, alter := range map[string]func(*Options){
		"wrong agent":     func(o *Options) { o.Subject.ID = "rca-" + strings.Repeat("b", 32) },
		"managed subject": func(o *Options) { o.Subject.ID = "hri-" + strings.Repeat("a", 32) },
		"wrong platform":  func(o *Options) { o.Platform = "workbuddy" },
		"expired":         func(o *Options) { end := now; o.ExpiresAt = &end },
		"long":            func(o *Options) { end := until.Add(time.Nanosecond); o.ExpiresAt = &end },
		"unbounded":       func(o *Options) { o.ExpiresAt = nil },
		"advisory":        func(o *Options) { o.EnforcementMode = "warn" },
	} {
		t.Run(name, func(t *testing.T) {
			copy := opts
			alter(&copy)
			if _, err := BuildRuntimeCheckDraft(adm.Admission, copy, id); err == nil {
				t.Fatal("unsafe temporary draft accepted")
			}
		})
	}
	bad := adm.Admission
	bad.SkillName = "unrelated"
	if _, err := BuildRuntimeCheckDraft(bad, opts, id); err == nil {
		t.Fatal("tampered admission accepted")
	}
	if _, err := BuildInstanceDraft(adm.Admission, opts, "operator", "gid-"+strings.Repeat("a", 32)); err == nil {
		t.Fatal("ordinary instance builder accepted rca")
	}
}
