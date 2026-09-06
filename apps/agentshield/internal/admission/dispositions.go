package admission

import (
	"path"
	"strings"
)

// Category / disposition vocabulary — must match admission.schema.json enums.
const (
	catDeception   = "user_deception"
	catHidden      = "hidden_instruction"
	catInjection   = "prompt_injection"
	catExfil       = "credential_exfil"
	catIntegrity   = "integrity"
	catCapability  = "capability_declaration"
	catDangerous   = "dangerous_code"
	catPersistence = "persistence"
	catSupplyChain = "supply_chain"
	catInfo        = "info"

	dispQuarantine = "quarantine"
	dispDeclare    = "declare"
	dispInfo       = "info"
)

// fileZone classifies where in the skill a hit lives. Instructions the model
// will actually execute (SKILL.md body, scripts/) are held to the strict
// table; documentation zones (references/, evals/, assets/) only inform.
type fileZone int

const (
	zoneSkillMD fileZone = iota
	zoneScripts
	zoneDocs
	zoneOther
)

func zoneOf(p string) fileZone {
	switch {
	case p == "SKILL.md":
		return zoneSkillMD
	case strings.HasPrefix(p, "scripts/"):
		return zoneScripts
	case strings.HasPrefix(p, "references/"), strings.HasPrefix(p, "evals/"), strings.HasPrefix(p, "assets/"),
		strings.HasPrefix(p, "docs/"), strings.HasSuffix(strings.ToLower(p), ".md") && p != "SKILL.md":
		return zoneDocs
	}
	return zoneOther
}

// declaredCapability describes the permission fact a "declare" finding yields.
type declaredCapability struct {
	domain, action, resType, resValue string
}

// classifyRuleHit maps a rulepack rule_id to (category, disposition, optional
// declared capability). fileHasEgress is true when the same file also contains
// a network sink (webhook/reverse shell/non-local URL) — spec §3.6.4:
// "credential read + egress in the same file" is exfiltration; a lone
// credential read is a capability declaration.
func classifyRuleHit(ruleID, filePath, excerpt, lineText string, fileHasEgress bool) (string, string, *declaredCapability) {
	cat, disp, capab := classifyCore(ruleID, filePath, excerpt, lineText, fileHasEgress)
	// Documentation *prose* zones only inform. Executable / structured code
	// under docs|references|evals|assets (H5b) keeps the core disposition —
	// directory name alone must not demote download-exec or credential sinks.
	if zoneOf(filePath) == zoneDocs && !isCodeFile(filePath) {
		return cat, dispInfo, nil
	}
	return cat, disp, capab
}

func classifyCore(ruleID, filePath, excerpt, lineText string, fileHasEgress bool) (string, string, *declaredCapability) {
	zone := zoneOf(filePath)
	switch {
	case ruleID == "threat-prompt-injection":
		switch {
		case zone == zoneScripts:
			return catInjection, dispQuarantine, nil
		case zone == zoneSkillMD && !isExampleLine(lineText):
			return catInjection, dispQuarantine, nil
		}
		return catInjection, dispInfo, nil

	case ruleID == "threat-net-webhook-exfil", ruleID == "threat-net-reverse-shell":
		return catExfil, dispQuarantine, nil

	case ruleID == "threat-net-hardcoded-c2":
		// confidence 0.8 < control-plane auto-quarantine threshold 0.85
		return catExfil, dispDeclare, &declaredCapability{"network", "socket.connect", "endpoint", firstToken(excerpt)}

	case strings.HasPrefix(ruleID, "threat-cred-"):
		if fileHasEgress {
			return catExfil, dispQuarantine, nil
		}
		return catExfil, dispDeclare, &declaredCapability{"credential", "credential.read", "credential_ref", credentialRef(ruleID)}

	case ruleID == "threat-persist-shell-rc":
		return catPersistence, dispQuarantine, nil
	case strings.HasPrefix(ruleID, "threat-persist-"):
		if strings.Contains(excerpt, "authorized_keys") {
			return catPersistence, dispQuarantine, nil
		}
		return catPersistence, dispDeclare, &declaredCapability{"filesystem", "fs.write", "path", persistTarget(ruleID)}

	case strings.HasPrefix(ruleID, "threat-download-exec-"), strings.HasPrefix(ruleID, "threat-obf-"), strings.HasPrefix(ruleID, "threat-py-"):
		return catDangerous, dispDeclare, &declaredCapability{"process", "process.exec", "tool", "shell"}
	}
	return catInfo, dispInfo, nil
}

func credentialRef(ruleID string) string {
	switch ruleID {
	case "threat-cred-ssh":
		return "~/.ssh"
	case "threat-cred-dotenv":
		return ".env"
	case "threat-cred-system-files":
		return "/etc/passwd,/etc/shadow"
	case "threat-cred-cloud":
		return "~/.aws,~/.config/gcloud,~/.azure"
	case "threat-cred-browser-store":
		return "browser-credential-store"
	case "threat-cred-hardcoded-secret":
		return "hardcoded-literal"
	}
	return ruleID
}

func persistTarget(ruleID string) string {
	switch ruleID {
	case "threat-persist-crontab":
		return "crontab,/etc/cron.*"
	case "threat-persist-systemd":
		return "systemd-units"
	case "threat-persist-launchd":
		return "~/Library/LaunchAgents"
	case "threat-persist-run-key":
		return "HKCU\\...\\CurrentVersion\\Run"
	}
	return ruleID
}

// isExampleLine treats blockquotes and explicit "this is an example /
// do-not-follow" prose as examples the skill is warning about (main FP source
// on NVIDIA catalogues). Quote characters alone — including a wholly quoted
// line — are NOT enough (H5c): an attacker must not quarantine-bypass by
// wrapping a real instruction in quotes. Fenced blocks are handled by the
// caller via fence tracking.
func isExampleLine(line string) bool {
	t := strings.TrimSpace(line)
	if t == "" {
		return false
	}
	if strings.HasPrefix(t, ">") {
		return true
	}
	lower := strings.ToLower(t)
	for _, marker := range []string{
		"example of", "for example", "e.g.", "eg.",
		"should not follow", "do not follow", "don't follow",
		"red flag", "must not follow", "never follow",
		"you should not", "never tell the user",
	} {
		if strings.Contains(lower, marker) {
			return true
		}
	}
	return false
}

func firstToken(s string) string {
	f := strings.Fields(s)
	if len(f) == 0 {
		return s
	}
	return f[0]
}

// isCodeFile decides which files get homoglyph/identifier checks.
func isCodeFile(p string) bool {
	switch strings.ToLower(path.Ext(p)) {
	case ".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".ps1", ".psm1", ".rb", ".go", ".yaml", ".yml", ".json", ".toml":
		return true
	}
	return strings.HasPrefix(p, "scripts/")
}
