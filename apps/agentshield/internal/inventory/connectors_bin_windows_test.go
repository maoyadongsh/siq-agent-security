package inventory

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/linktest"
)

func windowsConnectorLayouts(root string) []string {
	return []string{
		filepath.Join(root, "hermes", "hermes-connector.exe"),
		filepath.Join(root, "hermes", "hermes.exe"),
		filepath.Join(root, "hermes-connector.exe"),
		filepath.Join(root, "hermes.exe"),
	}
}

func TestFindConnectorBinWindowsLayouts(t *testing.T) {
	for i := 0; i < 4; i++ {
		t.Run([]string{"nested-connector", "nested-name", "root-connector", "root-name"}[i], func(t *testing.T) {
			root := filepath.Join(t.TempDir(), "connector directory with spaces")
			want := windowsConnectorLayouts(root)[i]
			// Discovery checks a regular file, not POSIX execute bits or PE validity.
			write(t, want, "fixed candidate; execution is tested separately")
			got, err := findConnectorBin(root, "hermes")
			if err != nil || got != want || !filepath.IsAbs(got) {
				t.Fatalf("got %q, %v; want explicit %q", got, err, want)
			}
		})
	}
}

func TestFindConnectorBinWindowsPriority(t *testing.T) {
	root := t.TempDir()
	paths := windowsConnectorLayouts(root)
	for _, path := range paths {
		write(t, path, "fixed candidate")
	}
	for _, want := range paths {
		got, err := findConnectorBin(root, "hermes")
		if err != nil || got != want {
			t.Fatalf("got %q, %v; want next candidate %q", got, err, want)
		}
		if err := os.Remove(want); err != nil {
			t.Fatal(err)
		}
	}
	if got, err := findConnectorBin(root, "hermes"); got != "" || !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("removed candidates: got %q, %v", got, err)
	}
}

func TestFindConnectorBinWindowsRejectsDirectories(t *testing.T) {
	root := t.TempDir()
	for _, path := range windowsConnectorLayouts(root) {
		if err := os.MkdirAll(path, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	if got, err := findConnectorBin(root, "hermes"); got != "" || !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("directories accepted: %q, %v", got, err)
	}
}

func TestFindConnectorBinWindowsRejectsScriptsAndPATHEXT(t *testing.T) {
	root := t.TempDir()
	t.Setenv("PATHEXT", ".COM;.BAT;.CMD;.PS1;.PY;.EXE")
	for _, stem := range []string{filepath.Join(root, "hermes", "hermes-connector"), filepath.Join(root, "hermes", "hermes"), filepath.Join(root, "hermes-connector")} {
		for _, suffix := range []string{"", ".com", ".bat", ".cmd", ".ps1", ".py", ".exe.cmd"} {
			write(t, stem+suffix, "#!/usr/bin/env python3\n# must never execute\n")
		}
	}
	if got, err := findConnectorBin(root, "hermes"); got != "" || !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("script/PATHEXT accepted: %q, %v", got, err)
	}
}

func TestFindConnectorBinWindowsRejectsSymlink(t *testing.T) {
	root := t.TempDir()
	target := filepath.Join(t.TempDir(), "owned-target.exe")
	write(t, target, "fixed candidate outside the connector directory")
	linktest.Symlink(t, target, filepath.Join(root, "hermes.exe"))
	if got, err := findConnectorBin(root, "hermes"); got != "" || !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("symlink candidate accepted: %q, %v", got, err)
	}
}

func TestFindConnectorBinWindowsExplicitDotRootDoesNotUsePATH(t *testing.T) {
	root, shadow := t.TempDir(), t.TempDir()
	local := installConnectorFixture(t, filepath.Join(root, "hermes"), connectorFixture{WithCollect: true, CandidateID: "connector:local"})
	installConnectorFixture(t, filepath.Join(shadow, "hermes"), connectorFixture{WithCollect: true, CandidateID: "connector:path-shadow"})
	old, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(root); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := os.Chdir(old); err != nil {
			t.Error(err)
		}
	})
	t.Setenv("PATH", shadow)
	bin, err := findConnectorBin(".", "hermes")
	if err != nil || bin != local || !filepath.IsAbs(bin) {
		t.Fatalf("explicit root lost: %q, %v; want %q", bin, err, local)
	}
	batch, err := execConnector(bin, "hermes", root)
	if err != nil || len(batch.Candidates) != 1 || batch.Candidates[0].CandidateID != "connector:local" {
		t.Fatalf("local native fixture not executed: candidates=%v error=%v", batch.Candidates, err)
	}
	if err := os.Remove(local); err != nil {
		t.Fatal(err)
	}
	if bin, err := findConnectorBin(".", "hermes"); bin != "" || !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("missing local candidate fell back to PATH: %q, %v", bin, err)
	}
}

func TestFindConnectorBinWindowsRejectsRedirectedAncestors(t *testing.T) {
	for _, kind := range []string{"nested", "root", "above-root"} {
		t.Run(kind, func(t *testing.T) {
			root, outside := t.TempDir(), t.TempDir()
			link := filepath.Join(root, "hermes")
			name := "hermes-connector.exe"
			if kind != "nested" {
				link = filepath.Join(root, "redirect")
			}
			searchRoot := root
			if kind == "root" {
				searchRoot = link
			}
			if kind == "above-root" {
				searchRoot = filepath.Join(link, "ordinary")
				name = filepath.Join("ordinary", name)
			}
			write(t, filepath.Join(outside, name), "external candidate must not execute")
			if err := linktest.Directory(outside, link); err != nil {
				t.Fatal(err)
			}
			defer os.Remove(link)
			if got, err := findConnectorBin(searchRoot, "hermes"); got != "" || !errors.Is(err, os.ErrNotExist) {
				t.Fatalf("redirected ancestor accepted: %q, %v", got, err)
			}
			raw, err := os.ReadFile(filepath.Join(outside, name))
			if err != nil || string(raw) != "external candidate must not execute" {
				t.Fatal("outside candidate changed", err)
			}
		})
	}
}
