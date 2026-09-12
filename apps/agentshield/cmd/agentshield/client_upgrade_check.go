package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"siq-agent-security/apps/agentshield/internal/clientrelease"
)

func cmdClientUpgradeCheck(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("client-upgrade-check", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	manifest := fs.String("manifest", "", "signed v2 release manifest")
	binary := fs.String("binary", "", "candidate binary")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *manifest == "" || *binary == "" || fs.NArg() != 0 {
		return errors.New("client-upgrade-check: --manifest FILE --binary FILE required")
	}
	version, err := clientrelease.CheckUpgrade(*manifest, *binary)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(out, "候选 %s 的发行签名、内容与无迁移兼容声明预检通过；尚未批准或切换运行版本。\n", version)
	return err
}
