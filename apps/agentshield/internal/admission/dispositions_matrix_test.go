package admission

import (
	"testing"

	"siq-agent-security/apps/agentshield/internal/rulepack"
)

// matrixRow freezes rule_id → category/disposition/declared capability for
// scripts/ (executable zone) with fileHasEgress=false unless noted.
// DEV06-F: capability facts and malicious quarantine must stay independent.
type matrixRow struct {
	ruleID      string
	category    string
	disposition string
	domain      string // empty when no declared capability
	action      string
	resType     string
	resValue    string
	note        string
}

// scriptsNoEgress is the primary capability→admission contract for rulepack rules.
var scriptsNoEgress = []matrixRow{
	{"threat-download-exec-pipe", catDangerous, dispDeclare, "process", "process.exec", "tool", "shell", "download|exec declare"},
	{"threat-download-exec-powershell", catDangerous, dispDeclare, "process", "process.exec", "tool", "shell", "PS download|exec declare"},
	{"threat-cred-ssh", catExfil, dispDeclare, "credential", "credential.read", "credential_ref", "~/.ssh", "lone cred read"},
	{"threat-cred-dotenv", catExfil, dispDeclare, "credential", "credential.read", "credential_ref", ".env", "lone cred read"},
	{"threat-cred-system-files", catExfil, dispDeclare, "credential", "credential.read", "credential_ref", "/etc/passwd,/etc/shadow", "lone cred read"},
	{"threat-cred-cloud", catExfil, dispDeclare, "credential", "credential.read", "credential_ref", "~/.aws,~/.config/gcloud,~/.azure", "lone cred read"},
	{"threat-cred-browser-store", catExfil, dispDeclare, "credential", "credential.read", "credential_ref", "browser-credential-store", "lone cred read"},
	{"threat-cred-hardcoded-secret", catExfil, dispDeclare, "credential", "credential.read", "credential_ref", "hardcoded-literal", "lone cred read"},
	{"threat-persist-crontab", catPersistence, dispDeclare, "filesystem", "fs.write", "path", "crontab,/etc/cron.*", "persist declare"},
	{"threat-persist-systemd", catPersistence, dispDeclare, "filesystem", "fs.write", "path", "systemd-units", "persist declare"},
	{"threat-persist-launchd", catPersistence, dispDeclare, "filesystem", "fs.write", "path", "~/Library/LaunchAgents", "persist declare"},
	{"threat-persist-run-key", catPersistence, dispDeclare, "filesystem", "fs.write", "path", "HKCU\\...\\CurrentVersion\\Run", "persist declare"},
	{"threat-persist-shell-rc", catPersistence, dispQuarantine, "", "", "", "", "shell-rc always quarantine"},
	{"threat-obf-base64-pipe-exec", catDangerous, dispDeclare, "process", "process.exec", "tool", "shell", "obfuscation declare"},
	{"threat-obf-eval-dynamic", catDangerous, dispDeclare, "process", "process.exec", "tool", "shell", "obfuscation declare"},
	{"threat-obf-base64-blob", catDangerous, dispDeclare, "process", "process.exec", "tool", "shell", "obfuscation declare"},
	{"threat-obf-py-marshal", catDangerous, dispDeclare, "process", "process.exec", "tool", "shell", "obfuscation declare"},
	{"threat-net-reverse-shell", catExfil, dispQuarantine, "", "", "", "", "egress sink quarantine"},
	{"threat-net-webhook-exfil", catExfil, dispQuarantine, "", "", "", "", "egress sink quarantine"},
	{"threat-net-hardcoded-c2", catExfil, dispDeclare, "network", "socket.connect", "endpoint", "203.0.113.1:4444", "sub-threshold declare"},
	{"threat-prompt-injection", catInjection, dispQuarantine, "", "", "", "", "scripts/ injection quarantine"},
	{"threat-py-os-system-regex", catDangerous, dispDeclare, "process", "process.exec", "tool", "shell", "py dangerous declare"},
	{"threat-py-subprocess-shell-regex", catDangerous, dispDeclare, "process", "process.exec", "tool", "shell", "py dangerous declare"},
	{"threat-py-ctypes-regex", catDangerous, dispDeclare, "process", "process.exec", "tool", "shell", "py dangerous declare"},
	{"threat-py-dangerous-import", catDangerous, dispDeclare, "process", "process.exec", "tool", "shell", "py dangerous declare"},
}

func TestCapabilityAdmissionMatrixCoversRulepack(t *testing.T) {
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string]bool{}
	for _, row := range scriptsNoEgress {
		seen[row.ruleID] = true
	}
	for _, rule := range pack.Rules {
		if !seen[rule.ID] {
			t.Errorf("rulepack rule %s missing from capability→admission matrix", rule.ID)
		}
	}
	if len(scriptsNoEgress) != len(pack.Rules) {
		t.Errorf("matrix rows=%d rulepack=%d", len(scriptsNoEgress), len(pack.Rules))
	}
}

func TestCapabilityAdmissionMatrixScriptsNoEgress(t *testing.T) {
	for _, row := range scriptsNoEgress {
		excerpt := row.resValue
		if row.ruleID == "threat-net-hardcoded-c2" {
			excerpt = "203.0.113.1:4444 connect"
		}
		cat, disp, cap := classifyRuleHit(row.ruleID, "scripts/setup.sh", excerpt, excerpt, false)
		if cat != row.category || disp != row.disposition {
			t.Errorf("%s: got (%s,%s) want (%s,%s) [%s]", row.ruleID, cat, disp, row.category, row.disposition, row.note)
		}
		if row.domain == "" {
			if cap != nil {
				t.Errorf("%s: expected nil capability, got %+v", row.ruleID, cap)
			}
			continue
		}
		if cap == nil {
			t.Errorf("%s: expected capability %s/%s, got nil", row.ruleID, row.domain, row.action)
			continue
		}
		if cap.domain != row.domain || cap.action != row.action || cap.resType != row.resType || cap.resValue != row.resValue {
			t.Errorf("%s: capability got %+v want {%s %s %s %s}", row.ruleID, cap, row.domain, row.action, row.resType, row.resValue)
		}
	}
}

func TestCapabilityAdmissionCredPlusEgressQuarantines(t *testing.T) {
	for _, id := range []string{
		"threat-cred-ssh", "threat-cred-dotenv", "threat-cred-system-files",
		"threat-cred-cloud", "threat-cred-browser-store", "threat-cred-hardcoded-secret",
	} {
		cat, disp, cap := classifyRuleHit(id, "scripts/exfil.sh", "secret", "secret", true)
		if cat != catExfil || disp != dispQuarantine || cap != nil {
			t.Errorf("%s+egress: got (%s,%s,%v) want quarantine without declared fact", id, cat, disp, cap)
		}
	}
}

func TestCapabilityAdmissionDocsProseDemotesInfo(t *testing.T) {
	cat, disp, cap := classifyRuleHit("threat-download-exec-pipe", "docs/guide.md", "curl|bash", "curl|bash", false)
	if disp != dispInfo || cap != nil {
		t.Fatalf("docs prose must demote to info without capability; got cat=%s disp=%s cap=%v", cat, disp, cap)
	}
}

func TestCapabilityAdmissionDocsCodeKeepsDeclare(t *testing.T) {
	cat, disp, cap := classifyRuleHit("threat-download-exec-pipe", "docs/setup.sh", "curl|bash", "curl|bash", false)
	if cat != catDangerous || disp != dispDeclare || cap == nil || cap.action != "process.exec" {
		t.Fatalf("docs code file must keep declare+capability; got cat=%s disp=%s cap=%v", cat, disp, cap)
	}
}

func TestCapabilityAdmissionPersistAuthorizedKeysQuarantine(t *testing.T) {
	cat, disp, cap := classifyRuleHit("threat-persist-crontab", "scripts/p.sh", "echo key >> ~/.ssh/authorized_keys", "authorized_keys", false)
	if cat != catPersistence || disp != dispQuarantine || cap != nil {
		t.Fatalf("authorized_keys persist must quarantine; got (%s,%s,%v)", cat, disp, cap)
	}
}
