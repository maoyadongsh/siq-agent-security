package main

import (
	"encoding/json"
	"errors"
	"flag"
	"io"

	"siq-agent-security/apps/agentshield/internal/state"
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
	w, err := state.AcquireWriter(dir)
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, w.Release()) }()
	st, err := state.Open(dir)
	if err != nil {
		return err
	}
	result, err := st.Initialize(w, *port)
	if err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(result)
}
