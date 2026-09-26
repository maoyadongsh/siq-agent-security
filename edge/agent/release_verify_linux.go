//go:build linux

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"os"

	"siq-agent-security/edge/agent/installplan"
)

func verifyEnterpriseRelease(args []string, output io.Writer) error {
	errInvalid := errors.New("enterprise_release_verification_failed")
	fs := flag.NewFlagSet("verify-enterprise-release", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	path := fs.String("release", "", "signed enterprise release envelope")
	bundle := fs.String("bundle", "", "optional absolute directory; verify every signed artifact")
	if fs.Parse(args) != nil || fs.NArg() != 0 || *path == "" {
		return errInvalid
	}
	raw, err := readInstallDocument(*path)
	if err != nil {
		return errInvalid
	}
	var release *installplan.Release
	if *bundle == "" {
		release, err = installplan.VerifyRelease(raw)
	} else {
		release, err = installplan.VerifyReleaseBundle(raw, *bundle)
	}
	if err != nil {
		return errInvalid
	}
	digest := sha256.Sum256(raw)
	return json.NewEncoder(output).Encode(struct {
		Schema            string `json:"schema_version"`
		Version           string `json:"version"`
		Commit            string `json:"source_commit"`
		Digest            string `json:"manifest_sha256"`
		SignatureVerified bool   `json:"publisher_signature_verified"`
		ArtifactsVerified bool   `json:"artifact_bytes_verified"`
		Installed         bool   `json:"installed"`
	}{"enterprise-release-verification/v1", release.Version, release.SourceCommit, hex.EncodeToString(digest[:]), true, *bundle != "", false})
}

func cmdVerifyEnterpriseRelease(args []string) error { return verifyEnterpriseRelease(args, os.Stdout) }
