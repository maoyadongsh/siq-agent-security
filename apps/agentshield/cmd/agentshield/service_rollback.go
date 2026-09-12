package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/clientrelease"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func cmdServiceRollback(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("service-rollback", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	original := fs.String("transaction", "", "original upgrade transaction")
	manifest := fs.String("manifest", "", "signed prior release manifest")
	binary := fs.String("binary", "", "prior binary at its original location")
	confirm := fs.Bool("confirm-rollback", false, "confirm interruption and source configuration restoration")
	restore := fs.Bool("restore-missing-binary", false, "restore missing historical executable from verified local snapshot")
	recoverID := fs.String("recover", "", "resume rollback transaction")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if runtime.GOOS != "linux" {
		return errors.New("service-rollback: Linux user service integration required")
	}
	if !*confirm || *original == "" || *binary == "" || fs.NArg() != 0 {
		return errors.New("回退会短暂停止保护；请提供 --transaction ID --binary OLD --confirm-rollback；可用 --manifest OLD 指定旧发行清单")
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	dir, err = filepath.Abs(dir)
	if err == nil {
		dir, err = filepath.EvalSymlinks(dir)
	}
	if err != nil {
		return err
	}
	st := &state.Store{Dir: dir}
	key, err := signing.LoadExisting(st.Dir)
	if err != nil {
		return err
	}
	plan, err := st.ReadServiceSwitch(key, *original)
	if err != nil {
		return err
	}
	if *manifest == "" {
		if plan.BinaryBindings == nil {
			return errors.New("service-rollback: legacy transaction lacks historical binary identity")
		}
		candidate := *binary
		if _, statErr := os.Lstat(candidate); errors.Is(statErr, os.ErrNotExist) && *restore {
			candidate, err = clientrelease.SnapshotPath(st.Dir, plan.BinaryBindings.SourceSHA256)
			if err != nil {
				return err
			}
		}
		*manifest, err = clientrelease.RetainedManifest(st.Dir, plan.BinaryBindings.SourceSHA256, candidate)
		if err != nil {
			return err
		}
	}
	oldPath, version, err := prepareRollbackBinary(st, plan, *binary, *manifest, *restore, clientrelease.CheckUpgrade)
	if err != nil {
		return err
	}
	unit := plan.SourceUnit
	recheck := func() error {
		v, err := clientrelease.CheckUpgrade(*manifest, oldPath)
		if err != nil {
			return err
		}
		if v != version {
			return errors.New("service-rollback: prior release changed")
		}
		return nil
	}
	ready := func() error {
		cfg, err := st.LoadConfig()
		if err != nil {
			return err
		}
		client := localClient()
		defer client.CloseIdleConnections()
		health, err := probeLocalInstance(client, fmt.Sprintf("http://127.0.0.1:%d", cfg.Port), st)
		if err != nil {
			return err
		}
		if health.Version != version {
			return errors.New("service-rollback: running release version mismatch")
		}
		return nil
	}
	check := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: plan.BinaryBindings.TargetSHA256, TargetSHA256: plan.BinaryBindings.SourceSHA256}, targetPath: oldPath}
	return rollbackUserService(st, *original, []byte(unit), *recoverID, out, runUserSystemctl, recheck, ready, check)
}
func rollbackUserService(st *state.Store, original string, unit []byte, recoverID string, out io.Writer, control userSystemctl, recheck, ready func() error, checks ...*serviceBinaryCheck) error {
	key, err := signing.LoadExisting(st.Dir)
	if err != nil {
		return err
	}
	plan, err := st.ReadServiceSwitch(key, original)
	if err != nil {
		return err
	}
	if string(unit) != plan.SourceUnit {
		return errors.New("service-rollback: candidate does not reproduce original source configuration")
	}
	if plan.BinaryBindings != nil {
		expected := state.ServiceBinaryBindings{SourceSHA256: plan.BinaryBindings.TargetSHA256, TargetSHA256: plan.BinaryBindings.SourceSHA256}
		if len(checks) != 1 || checks[0] == nil || checks[0].bindings != expected {
			return errors.New("service-rollback: historical binary identity mismatch")
		}
	} else if len(checks) != 0 {
		return errors.New("service-rollback: legacy transaction lacks historical binary identity")
	}
	if err = switchUserService(st, []byte(plan.TargetUnit), unit, recoverID, out, control, recheck, ready, true, checks...); err != nil {
		return fmt.Errorf("service-rollback: retain --transaction %s when recovering: %w", original, err)
	}
	return nil
}

// The plan must already be authenticated by ReadServiceSwitch. The verifier is
// supplied only by internal tests; the product command uses the release root.
func prepareRollbackBinary(st *state.Store, plan state.ServiceSwitch, binary, manifest string, restore bool, verify func(string, string) (string, error)) (string, string, error) {
	if plan.BinaryBindings == nil {
		return "", "", errors.New("service-rollback: legacy transaction lacks historical binary identity")
	}
	path, err := filepath.Abs(binary)
	if err != nil {
		return "", "", err
	}
	parent, err := filepath.EvalSymlinks(filepath.Dir(path))
	if err != nil {
		return "", "", err
	}
	path = filepath.Join(parent, filepath.Base(path))
	unit, err := renderUserUnit(path, st.Dir)
	if err != nil || unit != plan.SourceUnit {
		return "", "", errors.New("service-rollback: binary path differs from historical source")
	}
	info, statErr := os.Lstat(path)
	if statErr == nil && !info.Mode().IsRegular() {
		return "", "", errors.New("service-rollback: historical path is not a regular file")
	}
	if errors.Is(statErr, os.ErrNotExist) && restore {
		lock, err := state.AcquireWriter(filepath.Join(st.Dir, "service-control"))
		if err != nil {
			return "", "", err
		}
		restoreErr := func() error {
			snapshot, err := clientrelease.SnapshotPath(st.Dir, plan.BinaryBindings.SourceSHA256)
			if err != nil {
				return err
			}
			if _, err = verify(manifest, snapshot); err != nil {
				return err
			}
			return clientrelease.RestoreSnapshot(st.Dir, plan.BinaryBindings.SourceSHA256, path)
		}()
		if err = errors.Join(restoreErr, lock.Release()); err != nil {
			return "", "", err
		}
	} else if statErr != nil {
		return "", "", statErr
	}
	if err := checkServiceBinary(path, plan.BinaryBindings.SourceSHA256); err != nil {
		return "", "", err
	}
	version, err := verify(manifest, path)
	return path, version, err
}
