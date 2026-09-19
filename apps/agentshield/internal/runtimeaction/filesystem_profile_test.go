package runtimeaction

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
)

func TestWindowsFilesystemProfileSharedLexicalVectors(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/contracts/windows-filesystem-profile-v1-cases.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Profile FilesystemProfile `json:"profile"`
		Cases   []struct {
			Group, Name, Input, Normalized string
			Reject                         bool
		} `json:"cases"`
	}
	if err := json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	if len(fixture.Cases) == 0 {
		t.Fatal("empty lexical fixture")
	}
	for _, tc := range fixture.Cases {
		t.Run(tc.Group+"/"+tc.Name, func(t *testing.T) {
			got, err := NormalizeResourceForProfile(fixture.Profile, "filesystem", tc.Input)
			if tc.Reject {
				if err != ErrResource || got != "" {
					t.Fatalf("invalid path produced a resource: %q, %v", got, err)
				}
			} else if err != nil || got != tc.Normalized {
				t.Fatalf("got %q, %v; want %q", got, err, tc.Normalized)
			}
		})
	}
}

func TestWindowsFilesystemProfileLengthAndUTF8Boundaries(t *testing.T) {
	for _, tc := range []struct {
		name, value string
		wantError   bool
	}{
		{"component255", "C:/" + strings.Repeat("a", 255), false},
		{"component256", "C:/" + strings.Repeat("a", 256), true},
		{"path259", "C:/a/" + strings.Repeat("b", 254), false},
		{"path260", "C:/a/" + strings.Repeat("b", 255), true},
		{"utf16-259", "C:/a/" + strings.Repeat("😀", 127), false},
		{"utf16-260", "C:/a/" + strings.Repeat("😀", 127) + "a", true},
		{"invalid-utf8", "C:/a\xff", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, err := NormalizeResourceForProfile(FilesystemWindowsLocalDriveV1, "filesystem", tc.value)
			if (err != nil) != tc.wantError {
				t.Fatalf("unexpected boundary result: %v", err)
			}
		})
	}
}

func TestWindowsProfileW01EquivalentResourcesKeepDistinctRawParams(t *testing.T) {
	a := map[string]any{"path": `C:\Fixture\a.txt`}
	b := map[string]any{"path": "c:/Fixture/a.txt"}
	da := DescribeForProfile(FilesystemWindowsLocalDriveV1, "write_file", a)
	db := DescribeForProfile(FilesystemWindowsLocalDriveV1, "write_file", b)
	if da.ResourceError != nil || db.ResourceError != nil || !reflect.DeepEqual(ResourceRefs(da.Resources), ResourceRefs(db.Resources)) {
		t.Fatal("equivalent Windows resource identities differ")
	}
	paramsDigest := func(params map[string]any) string {
		raw, err := canon.Marshal(params)
		if err != nil {
			t.Fatal(err)
		}
		sum := sha256.Sum256(raw)
		return hex.EncodeToString(sum[:])
	}
	ea := Envelope{Tool: "write_file", ToolCallID: "call-1", ParamsDigest: paramsDigest(a), ResourceRefs: ResourceRefs(da.Resources)}
	eb := ea
	eb.ParamsDigest = paramsDigest(b)
	if ea.ParamsDigest == eb.ParamsDigest || ActionID(ea) == ActionID(eb) {
		t.Fatal("equivalent resources erased the original parameter identity")
	}
	eb = ea
	eb.ToolCallID = "call-2"
	if ActionID(ea) == ActionID(eb) {
		t.Fatal("a different call reused the action identity")
	}
}

func TestWindowsProfileW10W11DoNotCollapseSiblingVolumeOrCase(t *testing.T) {
	// This protects resource identity only. Grant directory containment and the
	// on-disk case/reparse checks require their own authority/native tests.
	seen := map[string]bool{}
	for _, value := range []string{"C:/Fixture/a", "C:/FixtureOther/a", "D:/Fixture/a", "C:/fixture/a", "C:/Fixture/秘密/a", "C:/Fixture/秘密/A"} {
		d := DescribeForProfile(FilesystemWindowsLocalDriveV1, "read_file", map[string]any{"path": value})
		if d.ResourceError != nil || len(d.Resources) != 1 {
			t.Fatal("ordinary lexical target unavailable", d.ResourceError)
		}
		ref := ResourceRefs(d.Resources)[0].Digest
		if seen[ref] {
			t.Fatal("distinct resource spellings collapsed")
		}
		seen[ref] = true
	}
}

func TestWindowsProfileW12AllResourceFieldsAreValidated(t *testing.T) {
	for _, params := range []map[string]any{
		{"path": "C:/Fixture/a", "file_path": `C:\Fixture\a`},
		{"path": "C:/Fixture/a", "file_path": "C:/Fixture/b"},
	} {
		d := DescribeForProfile(FilesystemWindowsLocalDriveV1, "read_file", params)
		if d.ResourceError != nil {
			t.Fatal(d.ResourceError)
		}
		want := 2
		if params["file_path"] == `C:\Fixture\a` {
			want = 1
		}
		if len(d.Resources) != want || len(d.Paths) != want {
			t.Fatal("structured resources missing or duplicated")
		}
	}
	for _, params := range []map[string]any{
		{"path": "C:/Fixture/a", "file_path": "C:/Fixture/a:stream"},
		{"path": "C:/Fixture/a", "file_path": 42},
		{"path": "/posix/a", "file_path": "C:/Fixture/a"},
	} {
		d := DescribeForProfile(FilesystemWindowsLocalDriveV1, "read_file", params)
		if d.ResourceError != ErrResource || len(d.Resources) != 0 || len(ResourceRefs(d.Resources)) != 0 || len(d.Paths) != 0 {
			t.Fatal("invalid field produced partial resource references")
		}
	}
}

func TestWindowsProfileInvalidResourceCannotUseLegacyPathHints(t *testing.T) {
	params := map[string]any{"path": "~/fixture"}
	legacy := Describe("read_file", params)
	if legacy.ResourceError != ErrResource || len(legacy.Paths) == 0 {
		t.Fatal("legacy POSIX hint behavior changed")
	}
	profiled := DescribeForProfile(FilesystemWindowsLocalDriveV1, "read_file", params)
	if profiled.ResourceError != ErrResource || len(profiled.Resources) != 0 || len(profiled.Paths) != 0 {
		t.Fatal("invalid Windows resource retained usable legacy path hints")
	}
}

func TestWindowsProfileW13LegacyDescriptorStillRejectsWindows(t *testing.T) {
	params := map[string]any{"path": "C:/Fixture/a"}
	if d := Describe("read_file", params); d.ResourceError != ErrResource || len(d.Resources) != 0 {
		t.Fatal("legacy resource interpretation gained Windows authority")
	}
	if d := DescribeForProfile(FilesystemWindowsLocalDriveV1, "read_file", params); d.ResourceError != nil || len(d.Resources) != 1 {
		t.Fatal("explicit new profile did not resolve the ordinary path")
	}
}

func TestWindowsProfileW14IsExplicitAndPreservesOtherDomains(t *testing.T) {
	for _, profile := range []FilesystemProfile{"", "unknown/v1"} {
		if value, err := NormalizeResourceForProfile(profile, "filesystem", "C:/Fixture/a"); value != "" || err != ErrResource {
			t.Fatal("unknown profile defaulted to a usable resource")
		}
		if d := DescribeForProfile(profile, "read_file", map[string]any{"path": "C:/Fixture/a"}); d.ResourceError != ErrResource || len(d.Resources) != 0 {
			t.Fatal("unknown profile produced a descriptor resource")
		}
	}
	for _, tc := range []struct{ domain, value string }{
		{"filesystem", "/private/a/../report"},
		{"filesystem", "//server/share/report"},
		{"network", "https://EXAMPLE.COM./a"},
		{"message", "CaseSensitiveRecipient"},
	} {
		legacy, err := NormalizeResource(tc.domain, tc.value)
		profiled, gotErr := NormalizeResourceForProfile(FilesystemPOSIXV1, tc.domain, tc.value)
		if err != nil || gotErr != nil || legacy != profiled {
			t.Fatal("explicit POSIX interpretation changed old semantics")
		}
		if tc.domain != "filesystem" {
			got, err := NormalizeResourceForProfile(FilesystemWindowsLocalDriveV1, tc.domain, tc.value)
			if err != nil || got != legacy {
				t.Fatal("filesystem profile changed another domain")
			}
		}
	}
	if _, err := NormalizeResourceForProfile(FilesystemPOSIXV1, "filesystem", "C:/Fixture/a"); err != ErrResource {
		t.Fatal("explicit POSIX profile accepted a Windows path")
	}
}
