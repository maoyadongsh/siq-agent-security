package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"strconv"

	"siq-agent-security/apps/agentshield/internal/state"
)

// startLocal keeps the actual service in this process so that OS service
// managers can own its lifetime; it never detaches or signals another process.
func startLocal(args []string, out io.Writer, serve func([]string) error) error {
	fs := flag.NewFlagSet("start", flag.ContinueOnError)
	port := fs.Int("port", 0, "local port (preserve existing configuration)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	explicit := false
	fs.Visit(func(f *flag.Flag) { explicit = explicit || f.Name == "port" })
	if fs.NArg() != 0 || *port < 0 || *port > 65535 || (explicit && *port == 0) {
		return errors.New("start: expected optional --port in 1..65535")
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	st := &state.Store{Dir: dir}
	cfg, err := st.LoadConfig()
	if err != nil {
		return errors.New("start: configuration invalid; restore it before starting")
	}
	if !explicit {
		*port = cfg.Port
	}
	addr := net.JoinHostPort("127.0.0.1", strconv.Itoa(*port))
	client := localClient()
	defer client.CloseIdleConnections()
	health, healthErr := probeLocalInstance(client, "http://"+addr, st)
	if healthErr == nil {
		if cfg.Port != *port {
			return errors.New("start: configured port differs from the running service; inspect configuration before reuse")
		}
		return json.NewEncoder(out).Encode(health)
	}
	// Binding checks availability without interpreting an arbitrary dial failure
	// as an empty port. The real serve call must bind again and own the writer.
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return fmt.Errorf("start: port unavailable or occupied by an incompatible instance; check status: %w", healthErr)
	}
	if err := ln.Close(); err != nil {
		return errors.New("start: cannot release startup port probe")
	}
	portArgs := []string{"--port", strconv.Itoa(*port)}
	if err := cmdInitialize(portArgs, io.Discard); err != nil {
		return err
	}
	return serve(portArgs)
}
