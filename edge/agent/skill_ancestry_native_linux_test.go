//go:build linux

package main

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"os"
	"slices"
	"testing"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

// Explicit synthetic fixture bridge. The deterministic key matches edge_helpers.py;
// it is never installed as a real device identity or exported as private material.
func TestSkillAncestryNativeExport(t *testing.T) {
	inputPath := os.Getenv("SIQ_SKILL_ANCESTRY_INPUT")
	if inputPath == "" {
		t.Skip("isolated native fixture input not supplied")
	}
	data, err := os.ReadFile(inputPath)
	if err != nil || len(data) > 16384 {
		t.Fatal("invalid fixture input")
	}
	var input struct {
		Connector string          `json:"connector"`
		Identity  string          `json:"identity"`
		TaskID    string          `json:"task_id"`
		Scope     json.RawMessage `json:"scope"`
	}
	if strictDiscoveryJSON(data, &input) != nil {
		t.Fatal("invalid fixture schema")
	}
	var scope protocol.Scope
	if strictDiscoveryJSON(input.Scope, &scope) != nil {
		t.Fatal("invalid scope")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	connector, err := NewSubprocessConnector(ctx, input.Connector, SubprocessOptions{
		Name: "directory", Version: agentVersion, Timeout: 10 * time.Second,
		MaxOutputBytes: protocol.DefaultOutputLimitBytes, MaxStderrBytes: 1024,
	})
	if err != nil {
		t.Fatal("fixture connector failed to start")
	}
	defer connector.Close()
	caps, err := connector.Describe(ctx)
	if err != nil || caps.NetworkAccess || !slices.Contains(caps.Objects, "skill_manifest_ancestry_v2") {
		t.Fatal("v2 capability missing")
	}
	var collection protocol.SkillCollection
	err = connector.call(ctx, protocol.OpCollectSkillsV2, struct {
		Plan protocol.ScanPlan `json:"plan"`
	}{
		Plan: protocol.ScanPlan{Scope: &scope, Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 1 << 20}},
	}, &collection)
	if err != nil || collection.SchemaVersion != "enterprise-skill-collection/v2" {
		t.Fatal("native v2 collection failed")
	}
	seed := sha256.Sum256([]byte("siq-test-edge:" + input.Identity))
	signer, err := NewSignerFromSeed(base64.StdEncoding.EncodeToString(seed[:]))
	if err != nil {
		t.Fatal("fixture signer failed")
	}
	body, digest, err := prepareSkillUpload(input.TaskID, input.Scope, collection, signer)
	if err != nil {
		t.Fatal("native skill signing failed")
	}
	pub, err := signer.PublicKeyPEM()
	if err != nil {
		t.Fatal(err)
	}
	output, err := json.Marshal(struct {
		Body      json.RawMessage `json:"body"`
		Digest    string          `json:"digest"`
		PublicKey string          `json:"public_key_pem"`
	}{body, digest, pub})
	if err != nil {
		t.Fatal(err)
	}
	file, err := os.OpenFile(os.Getenv("SIQ_SKILL_ANCESTRY_OUTPUT"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		t.Fatal("fixture output already exists or unavailable")
	}
	defer file.Close()
	if _, err := file.Write(output); err != nil {
		t.Fatal(err)
	}
	if err := file.Sync(); err != nil {
		t.Fatal(err)
	}
}
