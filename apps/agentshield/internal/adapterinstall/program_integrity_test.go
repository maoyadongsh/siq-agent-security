package adapterinstall

import (
	"os"
	"path/filepath"
	"testing"
)

func TestProgramIntegrityDetectsChangeAndExplicitUpgrade(t *testing.T) {
	for _, platform := range []string{Hermes, OpenClaw, WorkBuddy} {
		t.Run(platform, func(t *testing.T) {
			o, _ := installedPlan(t, platform)
			if d := Inspect(o); d.ConfigurationState == "incomplete" {
				t.Fatalf("installation fixture incomplete: %+v", d)
			}
			putTestFile(t, o.Binary, []byte("#!/bin/sh\n# different development candidate\n"), 0700)
			if d := Inspect(o); d.ConfigurationState != "incomplete" || checkStatus(d, "installation_program") != "fail" {
				t.Fatalf("program replacement hidden: %+v", d)
			}
			if _, err := Install(o); err != nil {
				t.Fatal(err)
			}
			if d := Inspect(o); checkStatus(d, "installation_program") != "pass" {
				t.Fatalf("explicit upgrade not accepted: %+v", d)
			}
			if _, err := Uninstall(o); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestProgramIntegrityRejectsMissingAndDifferentPath(t *testing.T) {
	for _, kind := range []string{"missing", "other-path"} {
		t.Run(kind, func(t *testing.T) {
			o, _ := installedPlan(t, OpenClaw)
			if kind == "missing" {
				if err := os.Remove(o.Binary); err != nil {
					t.Fatal(err)
				}
			} else {
				o.Binary = filepath.Join(filepath.Dir(o.Binary), "other-binary")
				putTestFile(t, o.Binary, []byte("#!/bin/sh\n"), 0700)
			}
			if d := Inspect(o); d.ConfigurationState != "incomplete" || checkStatus(d, "installation_program") != "fail" {
				t.Fatalf("unbound program accepted: %+v", d)
			}
		})
	}
}

func TestProgramIntegrityLegacyMissingDigestIsUnknown(t *testing.T) {
	o := testOpts(t, OpenClaw)
	p := testPlan(t, o, "install")
	// Reproduce a valid legacy plan that did not yet bind the program digest.
	p.payload.BinaryDigest = ""
	var err error
	p.payload.View.PlanDigest, err = p.digest()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Apply(p); err != nil {
		t.Fatal(err)
	}
	d := Inspect(o)
	if checkStatus(d, "installation_program") != "unknown" || d.ConfigurationState != "needs_verification" {
		t.Fatalf("invented legacy program identity: %+v", d)
	}
}

func TestProgramIntegrityInterruptedUpgradeKeepsOldProgramIdentity(t *testing.T) {
	o, _ := installedPlan(t, OpenClaw)
	old := o.Binary
	o.Binary = filepath.Join(filepath.Dir(old), "next-binary")
	putTestFile(t, o.Binary, []byte("#!/bin/sh\n# next version\n"), 0700)
	p := testPlan(t, o, "install")
	if _, err := Apply(p); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(transactionPath(o.StateDir, p.payload.View.PlanID, ".end.json")); err != nil {
		t.Fatal(err)
	}
	if d := Inspect(o); d.ConfigurationState != "incomplete" {
		t.Fatal("unfinished upgrade accepted")
	}
	if _, err := Recover(o.StateDir, o.Platform); err != nil {
		t.Fatal(err)
	}
	if d := Inspect(o); checkStatus(d, "installation_program") != "fail" {
		t.Fatal("new identity survived rollback")
	}
	o.Binary = old
	if d := Inspect(o); checkStatus(d, "installation_program") != "pass" {
		t.Fatalf("old identity lost after rollback: %+v", d)
	}
}
