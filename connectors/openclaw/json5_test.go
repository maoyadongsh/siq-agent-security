package main

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

func TestJSON5ConfigMatchesJSONAndPreservesOriginalEvidence(t *testing.T) {
	root := t.TempDir()
	strict := `{"agents":{"entries":{"main":{"name":"writer","skills":["docs"]}}}}`
	relaxed := `/* fixture */ { agents: { entries: { main: {name: 'writer', skills: ['docs',],},},},} // end`
	before, err := defaultRoleCollect(t, root, strict)
	if err != nil {
		t.Fatal(err)
	}
	after, err := defaultRoleCollect(t, root, relaxed)
	if err != nil {
		t.Fatal(err)
	}
	if len(before.Candidates) != 1 || len(after.Candidates) != 1 {
		t.Fatal("role count changed")
	}
	var oldSource, newSource map[string]string
	if json.Unmarshal([]byte(before.Candidates[0].Attributes["framework_source"]), &oldSource) != nil || json.Unmarshal([]byte(after.Candidates[0].Attributes["framework_source"]), &newSource) != nil {
		t.Fatal("invalid framework source")
	}
	if oldSource["instance_key"] != newSource["instance_key"] || oldSource["config_sha256"] != before.Evidence[0].ContentHash || newSource["config_sha256"] != after.Evidence[0].ContentHash || oldSource["evidence_id"] != before.Evidence[0].EvidenceID || newSource["evidence_id"] != after.Evidence[0].EvidenceID {
		t.Fatal("framework source does not preserve instance and raw evidence")
	}
	// Raw evidence references intentionally differ. Compare every other field.
	newSource["config_sha256"], newSource["evidence_id"] = oldSource["config_sha256"], oldSource["evidence_id"]
	if !reflect.DeepEqual(oldSource, newSource) {
		t.Fatal("framework source semantics changed")
	}
	after.Candidates[0].Attributes["framework_source"] = before.Candidates[0].Attributes["framework_source"]
	if before.Candidates[0].CandidateID != after.Candidates[0].CandidateID || !reflect.DeepEqual(before.Candidates[0].Attributes, after.Candidates[0].Attributes) {
		t.Fatal("JSON5 changed role semantics")
	}
	if before.Evidence[0].ContentHash == after.Evidence[0].ContentHash || before.Evidence[0].EvidenceID == after.Evidence[0].EvidenceID {
		t.Fatal("original evidence lost")
	}
}

func TestJSON5SupportedDataForms(t *testing.T) {
	for _, body := range []string{
		`{agents: {defaults: {skills: ['docs',],},},}`,
		"\ufeff{\u00a0agents: {defaults: {}},}",
		`{\u0061gents: {defaults: {}},}`,
		`{agents /* note */ : {}, value: +2.5, hex: -0xFE, fraction: .5, trailing: 2., exponent: 2.e2}`,
		"{agents // note\n : {},}",
		"{agents:{entries:{main:{name:'wr\\\niter',skills:['do\\x63s']}}}}",
		`{agents:{entries:{main:{name:'a\'b',workspace:'https://fixture/a/*b*/'}}}}`,
	} {
		batch, err := defaultRoleCollect(t, t.TempDir(), body)
		if err != nil || len(batch.Candidates) != 1 {
			t.Fatalf("valid fixture rejected: %v", err)
		}
	}
}

func TestJSON5InvalidOrAmbiguousConfigRejected(t *testing.T) {
	for _, body := range []string{
		`{,}`, `[,]`, `{agents: {},,}`, `{agents: {}, agents: {}}`,
		`{agents:{}, \u0061gents:{}}`, `{agents: { $include: 'private.json' }}`,
		`{agents: {}, value: function(){}}`, `{agents:{}, value: process.env.SECRET}`,
		`{agents:{}, value: NaN}`, `{agents:{}, value: Infinity}`, `{agents:{}, value: 0x10000000000000000}`,
		`{agents:{}, value: 01}`, `{agents:{}, value: 'unterminated}`, `/* unterminated`,
		`{agents:{}, value: '\8'}`, "{agents:{}, value: 'line\nbreak'}", `{agents:{}} {}`,
		strings.Repeat("{nested:", 66) + "{}" + strings.Repeat("}", 66),
	} {
		batch, err := defaultRoleCollect(t, t.TempDir(), body)
		if err == nil || err.Error() != "openclaw_config_invalid" || len(batch.Candidates) != 0 {
			t.Fatalf("unsafe fixture accepted: %q %v", body, err)
		}
	}
}

func TestJSON5NormalizationBudgets(t *testing.T) {
	for _, body := range []string{strings.Repeat(" ", (16<<20)+1), "[" + strings.Repeat("0,", 140000) + "]"} {
		if _, err := normalizeConfigJSON5([]byte(body)); err == nil {
			t.Fatal("unbounded normalization")
		}
	}
}
