package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/state"
)

func cmdImportSkill(args []string, out io.Writer) error {
	flags := flag.NewFlagSet("import-skill", flag.ContinueOnError)
	path := flags.String("path", "", "local Skill directory or ZIP archive")
	url := flags.String("url", "", "public HTTPS ZIP download URL")
	archivePath := flags.String("archive-path", "", "relative Skill directory inside the downloaded archive")
	sha256 := flags.String("sha256", "", "optional expected SHA256 of the downloaded ZIP")
	kind := flags.String("kind", "local_dir", "local_dir or local_zip")
	actor := flags.String("actor", "", "operator recorded in the signed import")
	id := flags.String("id", "", "reuse the ID from a previous import for an idempotent retry")
	timeout := flags.Int("timeout", 60, "maximum preparation time in seconds (1..120)")
	if err := flags.Parse(args); err != nil {
		return err
	}
	kindSet := false
	flags.Visit(func(f *flag.Flag) {
		if f.Name == "kind" {
			kindSet = true
		}
	})
	if flags.NArg() != 0 || (*path == "") == (*url == "") || (*url != "" && kindSet) || (*path != "" && (*archivePath != "" || *sha256 != "")) || *actor == "" || (*kind != "local_dir" && *kind != "local_zip") || *timeout < 1 || *timeout > 120 {
		return errors.New("import-skill: exactly one of --path/--url and --actor required; --kind only for local paths; --archive-path/--sha256 only for URLs; timeout 1..120")
	}
	if *id == "" {
		var nonce [16]byte
		if _, err := rand.Read(nonce[:]); err != nil {
			return err
		}
		*id = "si-" + hex.EncodeToString(nonce[:])
	}
	dir, err := stateDir()
	if err != nil {
		return err
	}
	writer, err := state.AcquireWriter(dir)
	if err != nil {
		return err
	}
	defer writer.Release()
	key, err := signing.Load(dir)
	if err != nil {
		return err
	}
	pack, err := loadPack()
	if err != nil {
		return err
	}
	imports, err := skillimport.Open(dir, key, pack, Version)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(*timeout)*time.Second)
	defer cancel()
	var record *skillimport.Record
	var analysis *skillimport.Analysis
	var reused bool
	if *url != "" {
		record, analysis, reused, err = imports.CreateRemote(ctx, skillimport.RemoteCreateRequest{SchemaVersion: "local-skill-import-remote-create/v1", ImportID: *id, URL: *url, ArchivePath: *archivePath, ExpectedSHA256: *sha256, ActorID: *actor})
	} else {
		record, analysis, reused, err = imports.Create(ctx, skillimport.CreateRequest{SchemaVersion: "local-skill-import-create/v1", ImportID: *id, SourceKind: *kind, Path: *path, ActorID: *actor})
	}
	if err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(skillimport.NewResult(record, analysis, reused))
}
