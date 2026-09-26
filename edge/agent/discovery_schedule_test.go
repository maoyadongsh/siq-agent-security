package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"

	"siq-agent-security/edge/agent/canon"
)

func scheduleFixture(t *testing.T) (*State, DiscoverySchedule, time.Time) {
	t.Helper()
	s, _ := consentFixture(t)
	signer, err := NewSigner()
	if err != nil {
		t.Fatal(err)
	}
	s.SignerSeed = signer.SeedB64()
	s.PublicKeyPEM, err = signer.PublicKeyPEM()
	if err != nil {
		t.Fatal(err)
	}
	var plan map[string]any
	if json.Unmarshal(s.DiscoveryPlan, &plan) != nil {
		t.Fatal("fixture plan")
	}
	raw, err := canon.Marshal(plan)
	if err != nil {
		t.Fatal(err)
	}
	hash := sha256.Sum256(raw)
	value := DiscoverySchedule{Schema: "enterprise-discovery-schedule/v1", ID: "eds-" + strings.Repeat("a", 32),
		PlanDigest: hex.EncodeToString(hash[:]), Identity: s.DeviceIdentity, StartsAt: "2026-09-26T00:00:00Z",
		ExpiresAt: "2026-09-27T00:00:00Z", Interval: 900, MaxRuns: 4, Purpose: "discovery_only"}
	return s, value, time.Date(2026, 9, 26, 0, 0, 0, 123456789, time.UTC)
}

func TestDiscoveryScheduleStrictShape(t *testing.T) {
	_, schedule, _ := scheduleFixture(t)
	raw, _ := json.Marshal(schedule)
	if _, err := parseDiscoverySchedule(raw); err != nil {
		t.Fatal(err)
	}
	for _, invalid := range []string{
		strings.TrimSuffix(string(raw), "}") + `,"max_runs":4}`,
		strings.Replace(string(raw), `"max_runs":4`, `"Max_Runs":4`, 1),
		strings.Replace(string(raw), `"max_runs":4`, `"max_runs":null`, 1),
		strings.Replace(string(raw), `"max_runs":4`, `"max_runs":true`, 1),
		strings.Replace(string(raw), `"max_runs":4`, `"max_runs":"4"`, 1),
		strings.Replace(string(raw), `"max_runs":4`, `"max_runs":4.0`, 1),
		strings.Replace(string(raw), `"interval_seconds":900`, `"interval_seconds":899`, 1),
		strings.Replace(string(raw), `"max_runs":4`, `"max_runs":2881`, 1),
		strings.Replace(string(raw), `2026-09-27T00:00:00Z`, `2026-11-27T00:00:00Z`, 1),
		strings.Replace(string(raw), `2026-09-27T00:00:00Z`, `2026-02-30T00:00:00Z`, 1),
		strings.ReplaceAll(string(raw), `2026-`, `0000-`),
		strings.Replace(string(raw), `2026-09-27T00:00:00Z`, `2026-09-27T00:00:00.1234567Z`, 1),
		string(raw) + ` {}`, strings.Repeat(" ", 8193),
	} {
		if _, err := parseDiscoverySchedule([]byte(invalid)); err == nil {
			t.Fatal("invalid schedule accepted")
		}
	}
}

func TestDiscoverySchedulePreparationRequiresExactConsentAndState(t *testing.T) {
	for _, fault := range []string{"none", "unconfirmed", "device", "origin", "environment", "digest", "seed", "pub", "expired", "revision", "legacy"} {
		t.Run(fault, func(t *testing.T) {
			s, schedule, now := scheduleFixture(t)
			confirmed, revision := true, int64(0)
			switch fault {
			case "unconfirmed":
				confirmed = false
			case "device":
				schedule.Identity = "foreign"
			case "origin":
				s.ControlPlaneURL = "https://other.test"
			case "environment":
				s.EnvironmentID = "foreign"
			case "digest":
				schedule.PlanDigest = strings.Repeat("f", 64)
			case "seed":
				s.SignerSeed = "bad"
			case "pub":
				s.PublicKeyPEM = "bad"
			case "expired":
				now = now.Add(24 * time.Hour)
			case "revision":
				revision = -1
			case "legacy":
				s.DiscoveryPlan = nil
				s.DiscoveryPlanSHA256 = ""
			}
			before, _ := json.Marshal(s)
			request, err := prepareDiscoveryScheduleConfirmation(s, schedule, revision, confirmed, now)
			after, _ := json.Marshal(s)
			if string(before) != string(after) {
				t.Fatal("state mutated")
			}
			if fault != "none" {
				if err == nil {
					t.Fatal("invalid confirmation accepted")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			bytes, err := request.signedBytes()
			if err != nil || VerifySignature(s.PublicKeyPEM, bytes, request.Signature) != nil {
				t.Fatal("signature failed")
			}
			if request.ConfirmedAt != "2026-09-26T00:00:00.123456Z" {
				t.Fatal("microsecond timestamp mismatch")
			}
			request.Origin = "https://other.test"
			bytes, _ = request.signedBytes()
			if VerifySignature(s.PublicKeyPEM, bytes, request.Signature) == nil {
				t.Fatal("origin substitution accepted")
			}
		})
	}
}

func TestDiscoveryScheduleConfirmationWireExport(t *testing.T) {
	s, schedule, now := scheduleFixture(t)
	request, err := prepareDiscoveryScheduleConfirmation(s, schedule, 0, true, now)
	if err != nil {
		t.Fatal(err)
	}
	payload, err := request.signedBytes()
	if err != nil {
		t.Fatal(err)
	}
	if VerifySignature(s.PublicKeyPEM, payload, request.Signature) != nil {
		t.Fatal("signature failed")
	}
	if path := os.Getenv("SIQ_SCHEDULE_CONFIRM_OUTPUT"); path != "" {
		out, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			t.Fatal(err)
		}
		defer out.Close()
		if err = json.NewEncoder(out).Encode(map[string]any{"scope": "synthetic-go-confirmation",
			"intent": schedule, "request": request, "signed_bytes": string(payload), "public_key": s.PublicKeyPEM}); err != nil {
			t.Fatal(err)
		}
	}
}
