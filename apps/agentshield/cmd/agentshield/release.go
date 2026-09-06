package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/skillmanifest"
)

func cmdReleaseManifest(args []string) error {
	fs := flag.NewFlagSet("release-manifest", flag.ContinueOnError)
	skillDir := fs.String("skill-dir", "", "skills/"+product.Name+" directory (default: discover)")
	binDir := fs.String("bin-dir", "", "directory of cross-compiled binaries (required unless --build)")
	out := fs.String("out", "", "output path (default: <skill-dir>/skill-manifest.json)")
	version := fs.String("version", skillmanifest.DefaultVersion, "skill and binary version")
	urlBase := fs.String("url-base", skillmanifest.DefaultURLBase, "unpublished GitHub Release URL prefix")
	doBuild := fs.Bool("build", false, "cross-compile four targets into --bin-dir before hashing")
	writeBootstrap := fs.Bool("write-bootstrap", false, "embed the signing public key in bootstrap.sh and bootstrap.ps1")
	if err := fs.Parse(args); err != nil {
		return err
	}

	key, err := skillmanifest.KeyFromEnv()
	if err != nil {
		return err
	}

	dir := *skillDir
	if dir == "" {
		dir, err = skillmanifest.FindSkillDir()
		if err != nil {
			return err
		}
	}
	dir, err = filepath.Abs(dir)
	if err != nil {
		return err
	}

	if *writeBootstrap {
		if err := skillmanifest.EmbedReleasePubkey(dir, key.PublicBase64()); err != nil {
			return err
		}
	}
	if key.PublicBase64() != skillmanifest.ReleasePublicKeyB64 {
		fmt.Fprintf(os.Stderr, "siq-agent-security: warning: signing key public half %s does not match ReleasePublicKeyB64; update the constant and bootstrap before publishing\n", key.PublicBase64())
	}

	if *doBuild {
		if *binDir == "" {
			*binDir = filepath.Join(os.TempDir(), "siq-agent-security-release-bin")
		}
		if err := os.MkdirAll(*binDir, 0o755); err != nil {
			return err
		}
		if err := crossCompile(*binDir, *version); err != nil {
			return err
		}
	}
	if *binDir == "" {
		return fmt.Errorf("release-manifest: --bin-dir is required (or pass --build)")
	}

	arts, err := hashArtifacts(*binDir, *urlBase)
	if err != nil {
		return err
	}
	contentHash, err := skillmanifest.HashSkillDir(dir)
	if err != nil {
		return err
	}
	m, err := skillmanifest.Build(skillmanifest.Options{
		Version:     *version,
		ContentHash: contentHash,
		Artifacts:   arts,
		SignedBy:    key.PublicBase64(),
	})
	if err != nil {
		return err
	}
	if err := skillmanifest.Sign(m, key); err != nil {
		return err
	}
	if err := skillmanifest.VerifyWithPublicKey(m, key.Public()); err != nil {
		return err
	}
	dest := *out
	if dest == "" {
		dest = filepath.Join(dir, "skill-manifest.json")
	}
	if err := skillmanifest.WriteFile(dest, m); err != nil {
		return err
	}
	fmt.Fprintf(os.Stderr, "siq-agent-security: wrote %s (content_hash %s signed_by %s)\n", dest, contentHash, m.SignedBy)
	return json.NewEncoder(os.Stdout).Encode(map[string]any{
		"path":         dest,
		"content_hash": contentHash,
		"signed_by":    m.SignedBy,
		"artifacts":    len(m.Binary.Artifacts),
	})
}

func cmdManifestVerify(args []string) error {
	fs := flag.NewFlagSet("manifest-verify", flag.ContinueOnError)
	if err := fs.Parse(args); err != nil {
		return err
	}
	path := fs.Arg(0)
	if path == "" {
		dir, err := skillmanifest.FindSkillDir()
		if err != nil {
			return err
		}
		path = filepath.Join(dir, "skill-manifest.json")
	}
	m, err := skillmanifest.LoadFile(path)
	if err != nil {
		return err
	}
	if err := skillmanifest.Verify(m); err != nil {
		return err
	}
	dir := filepath.Dir(path)
	got, err := skillmanifest.HashSkillDir(dir)
	if err != nil {
		return err
	}
	if got != m.Skill.ContentHash {
		return fmt.Errorf("manifest-verify: content_hash mismatch: manifest %s dir %s", m.Skill.ContentHash, got)
	}
	if err := skillmanifest.ValidateMatrix(m.SupportMatrix); err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{
		"path":         path,
		"verified":     true,
		"content_hash": got,
		"signed_by":    m.SignedBy,
	})
}

func hashArtifacts(binDir, urlBase string) ([]skillmanifest.Artifact, error) {
	urlBase = trimSlash(urlBase)
	var out []skillmanifest.Artifact
	for _, t := range skillmanifest.Targets {
		name := skillmanifest.ArtifactName(t.OS, t.Arch, t.Ext)
		p := filepath.Join(binDir, name)
		sum, n, err := skillmanifest.HashFile(p)
		if err != nil {
			return nil, fmt.Errorf("release-manifest: missing %s: %w", name, err)
		}
		out = append(out, skillmanifest.Artifact{
			OS:     t.OS,
			Arch:   t.Arch,
			SHA256: sum,
			URL:    urlBase + "/" + name,
			Bytes:  n,
		})
	}
	return out, nil
}

func crossCompile(binDir, version string) error {
	mod, err := skillmanifest.FindModuleRoot()
	if err != nil {
		return err
	}
	ldflags := "-s -w -X main.Version=" + version
	for _, t := range skillmanifest.Targets {
		name := skillmanifest.ArtifactName(t.OS, t.Arch, t.Ext)
		out := filepath.Join(binDir, name)
		cmd := exec.Command("go", "build", "-C", mod, "-trimpath", "-ldflags", ldflags, "-o", out, "./cmd/agentshield")
		cmd.Env = append(os.Environ(), "GOOS="+t.OS, "GOARCH="+t.Arch, "CGO_ENABLED=0")
		cmd.Stdout = os.Stderr
		cmd.Stderr = os.Stderr
		fmt.Fprintf(os.Stderr, "siq-agent-security: building %s/%s -> %s\n", t.OS, t.Arch, name)
		if err := cmd.Run(); err != nil {
			return fmt.Errorf("release-manifest: build %s/%s: %w", t.OS, t.Arch, err)
		}
	}
	return nil
}

func trimSlash(s string) string {
	for len(s) > 0 && s[len(s)-1] == '/' {
		s = s[:len(s)-1]
	}
	return s
}
