package main

import (
	"encoding/json"
	"errors"
	"flag"
	"io"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/product"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func cmdInitialize(args []string, out io.Writer) (resultErr error) {
	fs := flag.NewFlagSet("init", flag.ContinueOnError)
	port := fs.Int("port", 0, "initial local port (default 47611; preserve existing configuration)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 0 || *port < 0 || *port > 65535 {
		return errors.New("init: expected optional --port in 1..65535")
	}
	portSet := false
	fs.Visit(func(f *flag.Flag) {
		if f.Name == "port" {
			portSet = true
		}
	})
	if portSet && *port == 0 {
		return errors.New("init: port must be in 1..65535")
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	result, err := initializeLocalClient(dir, *port)
	if err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(result)
}

func initializeLocalClient(dir string, port int) (result state.InitializationResult, resultErr error) {
	if runtime.GOOS == "windows" && product.Env(product.EnvSigningSeed, product.EnvSigningSeedOld) != "" {
		return result, errors.New("init: Windows profile requires a persisted local identity; unset the signing seed override")
	}
	w, err := state.AcquireWriter(dir)
	if err != nil {
		return result, err
	}
	released := false
	defer func() {
		if !released {
			resultErr = errors.Join(resultErr, w.Release())
		}
	}()
	st, err := state.Open(dir)
	if err != nil {
		return result, err
	}
	result, err = st.Initialize(w, port)
	if err != nil {
		return result, err
	}
	if runtime.GOOS == "windows" && result.Fresh {
		// Establish the key before the activation journal becomes history. The
		// existing missing-key guard remains unchanged for non-pristine state.
		if _, err := signing.Load(dir); err != nil {
			return result, err
		}
		if err := w.Release(); err != nil {
			return result, err
		}
		released = true
		if _, err := st.ActivateWindowsProfile(true, Version); err != nil {
			return result, err
		}
	}
	if runtime.GOOS == "windows" {
		if err := requireWindowsInstallationProfile(dir); err != nil {
			return result, err
		}
	}
	return result, nil
}

func requireWindowsInstallationProfile(dir string) error {
	if err := stateformat.RequireWindowsProfile(dir); err != nil {
		return errors.Join(err, errors.New("Windows installation profile requires explicit recovery: use state-migrate --preview, confirm its exact invocation binding if migration is needed, then state-enable-windows-resources --confirm; existing grants are unchanged"))
	}
	return nil
}
