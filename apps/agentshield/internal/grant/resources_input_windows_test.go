package grant

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestResourceWindowsInput(t *testing.T) {
	legacy, initial, root := windowsResources(t)
	windows, _, err := PrepareWindowsResources(legacy, initial, true, key(t))
	if err != nil {
		t.Fatal(err)
	}
	// Component spelling, spaces and decomposed Unicode must survive unchanged.
	dir := filepath.Join(root, "Sub Folder e\u0301")
	if err := os.Mkdir(dir, 0700); err != nil {
		t.Fatal(err)
	}
	canonical := filepath.ToSlash(dir)
	canonical = strings.ToUpper(canonical[:1]) + canonical[1:]
	raw := strings.ToLower(canonical[:1]) + strings.ReplaceAll(canonical[1:], "/", `\`)
	for _, entry := range []string{"prepare", "edit"} {
		for _, access := range []string{"read_only", "read_write"} {
			t.Run(entry+"/"+access, func(t *testing.T) {
				source := legacy
				if entry == "edit" {
					source = windows
				}
				input := ResourceEdit{Tools: []string{"read_file", "write_file"}, Network: []NetworkPatch{}, Models: []string{},
					Filesystem: FilesystemPatch{ReadOnly: []string{}, ReadWrite: []string{}}}
				if access == "read_only" {
					input.Filesystem.ReadOnly = []string{raw}
				} else {
					input.Filesystem.ReadWrite = []string{raw}
				}
				before, _ := json.Marshal(source)
				inputBefore, _ := json.Marshal(input)
				var out Grant
				var policy DesiredPolicy
				var err error
				if entry == "prepare" {
					out, policy, err = PrepareWindowsResources(source, input, true, key(t))
				} else {
					out, policy, err = EditResources(source, input, key(t))
				}
				if err != nil {
					t.Fatal("legal Windows spelling rejected", err)
				}
				after, _ := json.Marshal(source)
				inputAfter, _ := json.Marshal(input)
				if !bytes.Equal(before, after) || !bytes.Equal(inputBefore, inputAfter) {
					t.Fatal("resource edit changed caller input or signed history")
				}
				if out.Status != "pending_approval" || out.ApprovedBy != nil || out.EffectiveReadback != nil ||
					!Verify(key(t).Public(), out) || RecheckFilesystemBindings(out) != nil {
					t.Fatal("normalization bypassed pending state, signature or live binding")
				}
				found := 0
				for _, fact := range out.Facts {
					if fact.Domain == "filesystem" && fact.Effect == "allow" {
						found++
						if fact.Resource.Value != canonical {
							t.Fatal("signed resource changed component spelling or kept separators")
						}
					}
				}
				if found == 0 || !reflect.DeepEqual(policy["filesystem"].(map[string]any)[access], []any{canonical}) {
					t.Fatal("canonical range missing from signed facts or desired policy")
				}
			})
		}
	}
}

func TestResourceWindowsInputRejects(t *testing.T) {
	legacy, initial, _ := windowsResources(t)
	windows, _, err := PrepareWindowsResources(legacy, initial, true, key(t))
	if err != nil {
		t.Fatal(err)
	}
	canonical := initial.Filesystem.ReadWrite[0]
	raw := strings.ToLower(canonical[:1]) + strings.ReplaceAll(canonical[1:], "/", `\`)
	cases := map[string][]string{
		"equivalent-duplicate": {canonical, raw},
		"trailing-space":       {raw + " "},
		"trailing-dot":         {raw + "."},
		"leading-space":        {" " + raw},
		"parent":               {raw + `\..`},
		"repeated-separator":   {raw + `\\child`},
		"unc":                  {`\\server\share`},
		"device":               {`\\?\C:\Fixture`},
		"ads":                  {raw + ":stream"},
		"relative":             {`Fixture\child`},
		"drive-relative":       {`C:Fixture`},
		"reserved":             {raw + `\COM¹.txt`},
		"invalid-utf8":         {raw + string([]byte{0xff})},
		"unicode-drive":        {"Ｃ" + raw[1:]},
		"control":              {raw + "\x00"},
		"long-path":            {canonical[:3] + strings.Repeat("a", 257)},
	}
	for name, paths := range cases {
		for _, access := range []string{"read_only", "read_write"} {
			t.Run(name+"/"+access, func(t *testing.T) {
				input := ResourceEdit{Tools: []string{}, Network: []NetworkPatch{}, Models: []string{},
					Filesystem: FilesystemPatch{ReadOnly: []string{}, ReadWrite: []string{}}}
				if access == "read_only" {
					input.Filesystem.ReadOnly = paths
				} else {
					input.Filesystem.ReadWrite = paths
				}
				before := append([]string{}, paths...)
				if _, _, err := PrepareWindowsResources(legacy, input, true, key(t)); err != ErrResourcesInvalid {
					t.Fatalf("prepare accepted invalid or duplicate input: %v", err)
				}
				if _, _, err := EditResources(windows, input, key(t)); err != ErrResourcesInvalid {
					t.Fatalf("edit accepted invalid or duplicate input: %v", err)
				}
				if !reflect.DeepEqual(paths, before) {
					t.Fatal("failed normalization changed caller input")
				}
			})
		}
	}
}

func TestResourceWindowsSignedBoundary(t *testing.T) {
	legacy, input, _ := windowsResources(t)
	before, _ := json.Marshal(legacy)
	digestBefore, err := PermissionDigest(legacy)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := EditResources(legacy, input, key(t)); err != ErrResourcesInvalid {
		t.Fatal("legacy POSIX edit inferred Windows interpretation", err)
	}
	if _, _, err := PrepareWindowsResources(legacy, input, false, key(t)); err != ErrFilesystemProfile {
		t.Fatal("normalization bypassed explicit profile confirmation", err)
	}
	after, _ := json.Marshal(legacy)
	digestAfter, err := PermissionDigest(legacy)
	if err != nil || !bytes.Equal(before, after) || digestBefore != digestAfter || !Verify(key(t).Public(), legacy) {
		t.Fatal("legacy signed bytes or permissions changed")
	}
	windows, _, err := PrepareWindowsResources(legacy, input, true, key(t))
	if err != nil {
		t.Fatal(err)
	}
	for i := range windows.Facts {
		if windows.Facts[i].Domain == "filesystem" && windows.Facts[i].Resource.Value != "*" {
			windows.Facts[i].Resource.Value = strings.ReplaceAll(windows.Facts[i].Resource.Value, "/", `\`)
		}
	}
	resign(key(t), &windows)
	if ValidateFilesystemProfile(windows) != ErrFilesystemProfile || Verify(key(t).Public(), windows) {
		t.Fatal("noncanonical signed facts were normalized into valid authority")
	}
	if _, _, err := EditResources(windows, input, key(t)); err != ErrFilesystemProfile {
		t.Fatal("resource editing accepted a malformed signed source", err)
	}
}
