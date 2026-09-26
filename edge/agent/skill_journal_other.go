//go:build !linux

package main

import "encoding/json"

func loadSkillUpload(*State, *Task) (*skillUploadRecord, error)    { return nil, errSkillJournal }
func saveSkillUpload(*State, *Task, json.RawMessage, string) error { return errSkillJournal }
