package skillmanifest

import "fmt"

// DefaultMatrix is the honest contest snapshot: no row is "supported"
// because Spark E2E evidence has not been archived yet. Trae is audit_only
// (no tool hook). L3 is claimed only on Linux, and only as experimental.
func DefaultMatrix() []Row {
	note := func(s string) string { return s }
	row := func(platform, osName string, tiers []string, status, n string, requires []string) Row {
		r := Row{Platform: platform, OS: osName, Tiers: tiers, Status: status, Note: n}
		if len(requires) > 0 {
			r.Requires = requires
		}
		return r
	}
	out := []Row{
		row("hermes", "linux", []string{"L0", "L1", "L2", "L3"}, "experimental",
			note("adapter + OpenShell CLI landed; Spark E2E pending"), nil),
		row("hermes", "darwin", []string{"L0", "L1", "L2"}, "experimental",
			note("L3 needs Docker Desktop; not evidenced"), nil),
		row("hermes", "windows", []string{"L0", "L1", "L2"}, "experimental",
			note("L3 needs WSL2; not evidenced"), nil),

		row("openclaw", "linux", []string{"L0", "L1", "L2", "L3"}, "experimental",
			note("policy-exec + plugin landed; no E2E evidence"), nil),
		row("openclaw", "darwin", []string{"L0", "L1", "L2"}, "experimental",
			note("L3 needs Docker Desktop; not evidenced"), nil),
		row("openclaw", "windows", []string{"L0", "L1", "L2"}, "experimental",
			note("L3 needs WSL2; not evidenced"), nil),

		row("codebuddy", "linux", []string{"L0", "L1", "L2"}, "experimental",
			note("hook landed; no E2E evidence"), nil),
		row("codebuddy", "darwin", []string{"L0", "L1", "L2"}, "experimental",
			note("hook landed; no E2E evidence"), nil),
		row("codebuddy", "windows", []string{"L0", "L1", "L2"}, "experimental",
			note("hook landed; no E2E evidence"), nil),

		row("trae", "linux", []string{"L0"}, "audit_only",
			note("no tool hook; cannot block"), nil),
		row("trae", "darwin", []string{"L0"}, "audit_only",
			note("no tool hook; cannot block"), nil),
		row("trae", "windows", []string{"L0"}, "audit_only",
			note("no tool hook; cannot block"), nil),

		row("claude_code", "linux", []string{"L0"}, "experimental",
			note("not this round"), nil),
		row("claude_code", "darwin", []string{"L0"}, "experimental",
			note("not this round"), nil),
		row("claude_code", "windows", []string{"L0"}, "experimental",
			note("not this round"), nil),

		row("codex", "linux", []string{"L0"}, "experimental",
			note("not this round"), nil),
		row("codex", "darwin", []string{"L0"}, "experimental",
			note("not this round"), nil),
		row("codex", "windows", []string{"L0"}, "experimental",
			note("not this round"), nil),
	}
	return out
}

// ValidateMatrix enforces the schema's honesty rules in Go so a bad release
// fails before the file is written. It is not a JSON Schema reimplementation
// of every field; it catches the rows that would lie to a judge.
func ValidateMatrix(rows []Row) error {
	if len(rows) < 1 {
		return fmt.Errorf("skillmanifest: support_matrix must not be empty")
	}
	for i, r := range rows {
		if r.Status == "supported" {
			return fmt.Errorf("skillmanifest: row %d (%s/%s) claims supported without archived evidence", i, r.Platform, r.OS)
		}
		if r.Status == "audit_only" {
			for _, t := range r.Tiers {
				if t != "L0" {
					return fmt.Errorf("skillmanifest: audit_only row %d must only list L0", i)
				}
			}
		}
		if hasTier(r.Tiers, "L2") && r.Status == "audit_only" {
			return fmt.Errorf("skillmanifest: audit_only must not claim L2")
		}
		if hasTier(r.Tiers, "L3") && (r.OS == "darwin" || r.OS == "windows") && len(r.Requires) == 0 {
			return fmt.Errorf("skillmanifest: L3 on %s requires a requires[] entry", r.OS)
		}
		if r.Platform == "trae" && r.Status != "audit_only" {
			return fmt.Errorf("skillmanifest: trae must be audit_only")
		}
	}
	return nil
}

func hasTier(tiers []string, want string) bool {
	for _, t := range tiers {
		if t == want {
			return true
		}
	}
	return false
}
