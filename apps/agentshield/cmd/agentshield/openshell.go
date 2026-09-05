package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/openshell"
	"siq-agent-security/apps/agentshield/internal/state"
)

type repeatedString []string

func (s *repeatedString) String() string { return strings.Join(*s, ",") }
func (s *repeatedString) Set(v string) error {
	*s = append(*s, v)
	return nil
}

func cmdOpenshell(args []string) error {
	if len(args) < 1 {
		return fmt.Errorf("openshell: usage: agentshield openshell probe|apply|doctor")
	}
	c := openshell.New(openshell.Options{ProbeTimeout: 5 * time.Second})
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	switch args[0] {
	case "doctor":
		return enc.Encode(c.Diagnose())
	case "probe":
		caps, err := c.Probe()
		if err != nil {
			return err
		}
		return enc.Encode(map[string]any{"ok": true, "tier": "L3", "capabilities": caps})
	case "apply":
		fs := flag.NewFlagSet("openshell apply", flag.ContinueOnError)
		target := fs.String("target", "", "sandbox / policy name")
		expected := fs.String("expected-revision", "", "compare-and-swap revision (empty = current)")
		var allows, denies repeatedString
		fs.Var(&allows, "allow", "host:port to allow (repeatable)")
		fs.Var(&denies, "deny", "host:port that must stay denied in readback (repeatable)")
		if err := fs.Parse(args[1:]); err != nil {
			return err
		}
		if *target == "" {
			return fmt.Errorf("openshell apply: --target is required")
		}
		if len(allows) == 0 {
			return fmt.Errorf("openshell apply: at least one --allow host:port is required")
		}
		var rules []openshell.NetworkRule
		for _, a := range allows {
			rules = append(rules, openshell.NetworkRule{Endpoint: a, Effect: "allow"})
		}
		dir, err := stateDir()
		if err != nil {
			return err
		}
		st, err := state.Open(dir)
		if err != nil {
			return err
		}
		result, err := c.ApplyAndVerify(*target, rules, *expected, allows, denies)
		if result.Readback.EvidenceID != "" {
			_ = st.PutEvidence(result.Readback.EvidenceID, map[string]any{
				"backend": "openshell", "revision": result.Receipt.BackendRevision,
				"snapshot_hash": result.Receipt.Evidence["snapshot_hash"], "target": *target,
				"verify_level": result.Report.Level,
			})
		}
		if err != nil {
			_ = enc.Encode(result)
			return err
		}
		return enc.Encode(result)
	default:
		return fmt.Errorf("openshell: unknown subcommand %q (probe|apply|doctor)", args[0])
	}
}
