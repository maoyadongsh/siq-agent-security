package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"time"

	"siq-agent-security/apps/agentshield/internal/decisionrelay"
)

func run(args []string) error {
	flags := flag.NewFlagSet("agentshield-decision-relay", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	configPath := flags.String("config", "", "absolute private relay config path")
	configFD := flags.Int("config-fd", -1, "already-open private relay config descriptor")
	if err := flags.Parse(args); err != nil || flags.NArg() != 0 || (*configPath == "") == (*configFD < 0) || *configFD == 0 || *configFD == 1 || *configFD == 2 || *configFD > 1024 {
		return errors.New("usage: agentshield-decision-relay (--config <absolute-path> | --config-fd <fd>)")
	}
	var cfg decisionrelay.Config
	var err error
	if *configPath != "" {
		cfg, err = decisionrelay.LoadConfig(*configPath)
	} else {
		configFile := os.NewFile(uintptr(*configFD), "openshell-decision-relay-config")
		if configFile == nil {
			return errors.New("decision relay: configuration unavailable")
		}
		defer configFile.Close()
		cfg, err = decisionrelay.LoadConfigFile(configFile)
	}
	if err != nil {
		return err
	}
	file := os.NewFile(uintptr(cfg.Listener.InheritedFD), "openshell-decision-relay-listener")
	if file == nil {
		return errors.New("decision relay: inherited listener unavailable")
	}
	listener, err := net.FileListener(file)
	_ = file.Close()
	if err != nil {
		return errors.New("decision relay: inherited listener unavailable")
	}
	defer listener.Close()
	listenerPort, err := cfg.ListenerPort()
	if err != nil {
		return errors.New("decision relay: invalid configuration")
	}
	expectedListener := net.JoinHostPort(cfg.Listener.GatewayIP, strconv.Itoa(listenerPort))
	if listener.Addr().Network() != "tcp" || listener.Addr().String() != expectedListener {
		return errors.New("decision relay: inherited listener is not the verified bridge endpoint")
	}
	handler, err := decisionrelay.New(cfg)
	if err != nil {
		return err
	}
	server := &http.Server{
		Handler:           handler,
		ReadHeaderTimeout: 2 * time.Second,
		ReadTimeout:       20 * time.Second,
		WriteTimeout:      25 * time.Second,
		IdleTimeout:       30 * time.Second,
		MaxHeaderBytes:    16 << 10,
	}
	stopped := make(chan error, 1)
	go func() { stopped <- server.Serve(listener) }()
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt)
	defer signal.Stop(signals)
	select {
	case err := <-stopped:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	case <-signals:
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		return server.Shutdown(ctx)
	}
}

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
