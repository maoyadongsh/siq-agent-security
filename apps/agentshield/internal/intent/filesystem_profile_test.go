package intent

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

func windowsContract() Contract {
	c := testContract()
	c.SchemaVersion, c.AuthorityKind, c.FilesystemProfile = "intent/v4", "instance_permission", string(runtimeaction.FilesystemWindowsLocalDriveV1)
	c.Authority.Issuer = "local-runtime-identity"
	return c
}

func TestWindowsIntentUsesComponentBoundaryAndRejectsAliases(t *testing.T) {
	c := windowsContract()
	c.ResourceConstraints = []ResourceConstraint{{Domain: "filesystem", Operator: "prefix", Value: "C:/Approved"}}
	for _, test := range []struct {
		path  string
		allow bool
	}{
		{`C:\Approved\report.txt`, true}, {"C:/Approved/report.txt", true},
		{"C:/ApprovedElsewhere/report.txt", false}, {"C:/approved/report.txt", false},
		{"C:/Approved/report.txt ", false}, {"C:/Approved/../outside", false},
		{`\\server\share\report.txt`, false}, {"/Approved/report.txt", false},
	} {
		err := c.Authorize("hermes", "a-1", "u-1", "read_file", map[string]any{"path": test.path}, time.Now())
		if (err == nil) != test.allow {
			t.Fatalf("%q: allow=%v, error=%v", test.path, test.allow, err)
		}
	}
	// Empty envelope constraints still cannot convert an invalid path into a
	// valid resource; the Grant supplies scope but not a second interpretation.
	c.ResourceConstraints = []ResourceConstraint{}
	if c.Authorize("hermes", "a-1", "u-1", "read_file", map[string]any{"path": "C:/Approved/file:stream"}, time.Now()) == nil {
		t.Fatal("alternate stream accepted without a resource constraint")
	}
}

func TestWindowsIntentCannotDowngradeOrUseRegex(t *testing.T) {
	for _, edit := range []func(*Contract){
		func(c *Contract) { c.Authority.Issuer = "model" },
		func(c *Contract) { c.SchemaVersion = "intent/v2" },
		func(c *Contract) { c.FilesystemProfile = "posix/v1" },
		func(c *Contract) { c.AuthorityKind = "task_intent" },
		func(c *Contract) {
			c.ResourceConstraints = []ResourceConstraint{{Domain: "filesystem", Operator: "regex", Value: ".*"}}
		},
		func(c *Contract) {
			c.ResourceConstraints = []ResourceConstraint{{Domain: "filesystem", Operator: "suffix", Value: "report.txt"}}
		},
	} {
		c := windowsContract()
		edit(&c)
		if c.Validate() == nil {
			t.Fatal("invalid Windows authority accepted")
		}
	}
}

func TestWindowsIntentWireAndBindingRejectProfileSmuggling(t *testing.T) {
	raw, err := json.Marshal(windowsContract())
	if err != nil {
		t.Fatal(err)
	}
	for _, bad := range []string{
		strings.Replace(string(raw), `"filesystem_profile":`, `"Filesystem_Profile":`, 1),
		strings.Replace(string(raw), `"intent/v4"`, `"intent/v2"`, 1),
		`{"schema_version":"intent/v4",` + string(raw)[1:],
		`{"provenance_refs":[],` + string(raw)[1:],
		`{"effect_requirements":[],` + string(raw)[1:],
		strings.Replace(string(raw), `"windows-local-drive/v1"`, `null`, 1),
	} {
		var c Contract
		if json.Unmarshal([]byte(bad), &c) == nil {
			t.Fatal("ambiguous profile contract decoded")
		}
	}
	ref := `{"grant_id":"g","admission_id":"a","permission_digest":"` + strings.Repeat("a", 64) + `","permission_digest_schema":"grant-permissions/v2"}`
	for _, bad := range []string{
		`{"grant_ref":` + ref + `}`,
		`{"schema_version":"intent-grant-binding/v2","grant_ref":` + strings.Replace(ref, `"grant-permissions/v2"`, `"grant-permissions/v1"`, 1) + `}`,
		`{"schema_version":"intent-grant-binding/v2","grant_ref":` + strings.Replace(ref, `"permission_digest_schema":`, `"Permission_Digest_Schema":`, 1) + `}`,
		`{"schema_version":null}`,
	} {
		var b Binding
		if json.Unmarshal([]byte(bad), &b) == nil {
			t.Fatal("mixed or ambiguous binding decoded")
		}
	}
}

func TestWindowsIntentNestedAuthorityFieldsAreExact(t *testing.T) {
	c := windowsContract()
	c.ResourceConstraints = []ResourceConstraint{{Domain: "filesystem", Operator: "prefix", Value: "C:/Approved"}}
	c.ParameterConstraints = []ParameterConstraint{{Path: "/payload", Operator: "equals", Value: map[string]any{
		"Issuer": "user data", "issuer": "also user data", "custom": map[string]any{"Task_ID": "payload"},
	}}}
	raw, err := json.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	t.Run("canonical and opaque parameter keys", func(t *testing.T) {
		var decoded Contract
		if err := json.Unmarshal(raw, &decoded); err != nil {
			t.Fatal(err)
		}
		if err := decoded.Validate(); err != nil || !reflect.DeepEqual(decoded, c) {
			t.Fatal("canonical contract or user parameter keys changed", err)
		}
	})
	for _, test := range []struct{ name, from, to string }{
		{"principal duplicate", `"principal":{"type":"user",`, `"principal":{"type":"user","type":"user",`},
		{"principal alias", `"principal":{"type":`, `"principal":{"Type":`},
		{"agent duplicate", `"agent":{"id":"a-1",`, `"agent":{"id":"a-1","id":"a-1",`},
		{"agent alias", `"agent":{"id":`, `"agent":{"ID":`},
		{"authority duplicate", `"authority":{"issuer":"local-runtime-identity",`, `"authority":{"issuer":"local-runtime-identity","issuer":"local-runtime-identity",`},
		{"authority alias", `"authority":{"issuer":`, `"authority":{"Issuer":`},
		{"resource duplicate", `"domain":"filesystem",`, `"domain":"filesystem","domain":"filesystem",`},
		{"resource alias", `"domain":"filesystem",`, `"Domain":"filesystem",`},
		{"parameter duplicate", `"path":"/payload",`, `"path":"/payload","path":"/payload",`},
		{"parameter alias", `"operator":"equals",`, `"Operator":"equals",`},
	} {
		t.Run(test.name, func(t *testing.T) {
			changed := strings.Replace(string(raw), test.from, test.to, 1)
			if changed == string(raw) {
				t.Fatal("fixture mutation did not apply")
			}
			var decoded Contract
			if json.Unmarshal([]byte(changed), &decoded) == nil {
				t.Fatal("ambiguous nested authority decoded")
			}
		})
	}
}

func TestWindowsIntentNestedStrictnessPreservesLegacyDecoding(t *testing.T) {
	for _, version := range []string{"intent/v2", "intent/v3"} {
		t.Run(version, func(t *testing.T) {
			c := testContract()
			c.SchemaVersion = version
			if version == "intent/v3" {
				constraints := []provenance.Constraint{}
				c.ProvenanceConstraints = &constraints
			}
			raw, err := json.Marshal(c)
			if err != nil {
				t.Fatal(err)
			}
			for _, changed := range []string{
				strings.Replace(string(raw), `"agent":{"id":"a-1",`, `"agent":{"id":"a-1","id":"a-1",`, 1),
				strings.Replace(string(raw), `"authority":{"issuer":`, `"authority":{"Issuer":`, 1),
			} {
				if changed == string(raw) {
					t.Fatal("fixture mutation did not apply")
				}
				var decoded Contract
				if err := json.Unmarshal([]byte(changed), &decoded); err != nil {
					t.Fatal("legacy decoding changed", err)
				}
				if err := decoded.Validate(); err != nil || !reflect.DeepEqual(decoded, c) {
					t.Fatal("legacy value changed", err)
				}
			}
		})
	}
}
