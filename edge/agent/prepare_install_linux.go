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
	"runtime"
	"syscall"
	"time"

	"siq-agent-security/edge/agent/installplan"
)

var errPrepareInstall = errors.New("install_preparation_failed")

type prepareOptions struct {
	plan, release, bundle, parent, tenant, environment, origin, confirmation, resume string
}

func cmdPrepareInstall(args []string) error {
	return prepareInstall(args, os.Stdout, time.Now().UTC(), runtime.GOARCH, installplan.StageBundle, installplan.VerifyStagedBundle)
}

// stage is dependency injection for offline tests only. The CLI always supplies
// the pinned-publisher implementation; no flag or environment can replace it.
func prepareInstall(args []string, output io.Writer, now time.Time, arch string, stage func(installplan.Plan, []byte, string, string) (string, error), resume func(installplan.Plan, []byte, string) error) error {
	var o prepareOptions
	fs := flag.NewFlagSet("prepare-install", flag.ContinueOnError)
	fs.SetOutput(io.Discard) // Parse errors must not echo untrusted arguments.
	fs.StringVar(&o.plan, "plan", "", "")
	fs.StringVar(&o.release, "release", "", "")
	fs.StringVar(&o.bundle, "bundle", "", "")
	fs.StringVar(&o.parent, "staging-parent", "", "")
	fs.StringVar(&o.resume, "resume-stage", "", "")
	fs.StringVar(&o.tenant, "tenant", "", "")
	fs.StringVar(&o.environment, "environment", "", "")
	fs.StringVar(&o.origin, "control-plane", "", "")
	fs.StringVar(&o.confirmation, "confirm-plan-sha256", "", "")
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			_, err := io.WriteString(output, "prepare-install --plan FILE --release FILE (--bundle DIR --staging-parent PRIVATE_DIR | --resume-stage DIR) --tenant ID --environment ID --control-plane ORIGIN --confirm-plan-sha256 DIGEST\nReview the authenticated plan and its discovery scope before confirming its exact file digest. Stages files only: no registration, scan, grants, or service activation.\n")
			return err
		}
		return errPrepareInstall
	}
	if fs.NArg() != 0 || (o.resume == "" && (o.bundle == "" || o.parent == "")) || (o.resume != "" && (o.bundle != "" || o.parent != "")) {
		return errPrepareInstall
	}
	raw, err := readInstallDocument(o.plan)
	if err != nil {
		return errPrepareInstall
	}
	h := sha256.Sum256(raw)
	if o.confirmation != hex.EncodeToString(h[:]) {
		return errPrepareInstall
	}
	p, err := installplan.Parse(raw)
	if err != nil || p.RequireCurrent(now, o.tenant, o.environment, o.origin, arch) != nil {
		return errPrepareInstall
	}
	release, err := readInstallDocument(o.release)
	if err != nil {
		return errPrepareInstall
	}
	path := o.resume
	if o.resume != "" {
		err = resume(*p, release, o.resume)
	} else {
		path, err = stage(*p, release, o.bundle, o.parent)
	}
	if err != nil {
		return errPrepareInstall
	}
	// This is explicitly not an installed/enrolled/protected status. A failed
	// output write can leave a complete stage; recovery must revalidate it.
	if err := json.NewEncoder(output).Encode(struct {
		Status     string `json:"status"`
		PlanID     string `json:"plan_id"`
		PlanSHA256 string `json:"plan_sha256"`
		StagePath  string `json:"stage_path"`
	}{"staged_only", p.PlanID, o.confirmation, path}); err != nil {
		return errPrepareInstall
	}
	return nil
}

func readInstallDocument(path string) ([]byte, error) {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, errPrepareInstall
	}
	f := os.NewFile(uintptr(fd), "install-document")
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Size() > installplan.MaxBytes {
		return nil, errPrepareInstall
	}
	raw, err := io.ReadAll(io.LimitReader(f, installplan.MaxBytes+1))
	if err != nil || len(raw) > installplan.MaxBytes {
		return nil, errPrepareInstall
	}
	return raw, nil
}
