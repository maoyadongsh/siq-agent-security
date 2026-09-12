package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"siq-agent-security/apps/agentshield/internal/clientrelease"
	"siq-agent-security/apps/agentshield/internal/state"
)

func cmdClientStage(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("client-stage", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	manifest := fs.String("manifest", "", "signed release manifest")
	binary := fs.String("binary", "", "candidate binary")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *manifest == "" || *binary == "" || fs.NArg() != 0 {
		return errors.New("client-stage: --manifest FILE --binary FILE required")
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	path, err := clientrelease.Stage(dir, *manifest, *binary)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(out, "已校验并暂存候选：%s\n尚未切换运行版本。\n", path)
	return err
}
