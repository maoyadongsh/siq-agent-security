package runtimecheck

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

const hermesLauncherMain = `# -*- coding: utf-8 -*-
import sys
from hermes_cli.main import main
if __name__ == "__main__":
    if sys.argv[0].endswith("-script.pyw"):
        sys.argv[0] = sys.argv[0][:-11]
    elif sys.argv[0].endswith(".exe"):
        sys.argv[0] = sys.argv[0][:-4]
    sys.exit(main())
`

var editableHermesLoader = regexp.MustCompile(`^import (__editable___hermes_agent_[A-Za-z0-9_]+_finder); ([A-Za-z0-9_]+)\.install\(\)\n?$`)
var editableHermesMapping = regexp.MustCompile(`(?m)^MAPPING: dict\[str, str\] = (\{[^\r\n]*\})$`)

// Supported Windows uv console launcher -> embedded Python path -> PEP 610
// editable-install metadata. This is read-only capability discovery, not a
// guess based on an adjacent directory and not an attestation of Python code.
// Unknown installation layouts are not silently treated as equivalent.
func inspectSyntheticInstallation(cli string) ([]modelSource, error) {
	launcher, raw, err := modelSourceRead(cli, false)
	if err != nil || launcher.info.IsDir() || len(raw) < 2 || !bytes.HasPrefix(raw, []byte("MZ")) {
		return nil, errModelUnsupported
	}
	z, err := zip.NewReader(bytes.NewReader(raw), int64(len(raw)))
	if err != nil || len(z.File) != 1 || z.File[0].Name != "__main__.py" || z.File[0].UncompressedSize64 > 16<<10 {
		return nil, errModelUnsupported
	}
	f, err := z.File[0].Open()
	if err != nil {
		return nil, errModelUnsupported
	}
	script, readErr := io.ReadAll(io.LimitReader(f, (16<<10)+1))
	closeErr := f.Close()
	if readErr != nil || closeErr != nil || len(script) > 16<<10 {
		return nil, errModelUnsupported
	}
	text := strings.ReplaceAll(string(script), "\r\n", "\n")
	first, body, ok := strings.Cut(text, "\n")
	if !ok || !strings.HasPrefix(first, "#!") || body != hermesLauncherMain {
		return nil, errModelUnsupported
	}
	python := strings.TrimPrefix(first, "#!")
	if !filepath.IsAbs(python) || filepath.Base(python) != "python.exe" || filepath.Base(filepath.Dir(python)) != "Scripts" {
		return nil, errModelUnsupported
	}
	venv := filepath.Dir(filepath.Dir(python))
	pins := []modelSource{launcher}
	for _, path := range []string{python, filepath.Join(venv, "pyvenv.cfg")} {
		pin, _, e := modelSourceRead(path, false)
		if e != nil || pin.info.IsDir() {
			return nil, errModelUnsupported
		}
		pins = append(pins, pin)
	}
	metadata, err := filepath.Glob(filepath.Join(venv, "Lib", "site-packages", "hermes_agent-*.dist-info", "direct_url.json"))
	if err != nil || len(metadata) != 1 {
		return nil, errModelUnsupported
	}
	meta, raw, err := modelSourceRead(metadata[0], false)
	if err != nil {
		return nil, errModelUnsupported
	}
	var direct struct {
		URL string `json:"url"`
		Dir struct {
			Editable bool `json:"editable"`
		} `json:"dir_info"`
	}
	if json.Unmarshal(raw, &direct) != nil || !direct.Dir.Editable {
		return nil, errModelUnsupported
	}
	u, err := url.Parse(direct.URL)
	if err != nil || u.Scheme != "file" || u.Host != "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return nil, errModelUnsupported
	}
	root := filepath.FromSlash(strings.TrimPrefix(u.Path, "/"))
	if !filepath.IsAbs(root) || !sameModelScopePath(filepath.Join(root, "venv"), venv) {
		return nil, errModelUnsupported
	}
	resolved, err := filepath.EvalSymlinks(root)
	if err != nil || !sameModelScopePath(resolved, root) {
		return nil, errModelUnsupported
	}
	pins = append(pins, meta)
	// PEP 610 provenance alone is not the import target. Cross-check the actual
	// generated editable import hook, without executing the .pth or Python file.
	loaders, e := filepath.Glob(filepath.Join(venv, "Lib", "site-packages", "__editable__.hermes_agent-*.pth"))
	if e != nil || len(loaders) != 1 {
		return nil, errModelUnsupported
	}
	loader, raw, e := modelSourceRead(loaders[0], false)
	if e != nil {
		return nil, errModelUnsupported
	}
	parts := editableHermesLoader.FindStringSubmatch(strings.ReplaceAll(string(raw), "\r\n", "\n"))
	if len(parts) != 3 || parts[1] != parts[2] {
		return nil, errModelUnsupported
	}
	finder, raw, e := modelSourceRead(filepath.Join(filepath.Dir(loaders[0]), parts[1]+".py"), false)
	if e != nil {
		return nil, errModelUnsupported
	}
	mappings := editableHermesMapping.FindAllSubmatch(raw, -1)
	if len(mappings) != 1 {
		return nil, errModelUnsupported
	}
	// This recognized setuptools literal contains string-only paths. Quotes or
	// expressions outside the JSON-equivalent subset fail, rather than eval.
	var mapping map[string]string
	if json.Unmarshal(bytes.ReplaceAll(mappings[0][1], []byte("'"), []byte(`"`)), &mapping) != nil || !sameModelScopePath(mapping["hermes_cli"], filepath.Join(root, "hermes_cli")) {
		return nil, errModelUnsupported
	}
	pins = append(pins, loader, finder)
	for _, path := range []string{root, filepath.Join(root, "hermes_cli", "main.py"), filepath.Join(root, "hermes_cli", "env_loader.py"), filepath.Join(root, "hermes_cli", "managed_scope.py")} {
		pin, _, e := modelSourceRead(path, false)
		if e != nil {
			return nil, errModelUnsupported
		}
		pins = append(pins, pin)
	}
	for _, name := range []string{".env", ".op.env"} {
		path := filepath.Join(root, name)
		if _, e := os.Lstat(path); !os.IsNotExist(e) {
			return nil, errModelUnsupported
		}
		pins = append(pins, modelSource{path: path})
	}
	for _, pin := range pins {
		if pin.verify() != nil {
			return nil, errModelScope
		}
	}
	return pins, nil
}
