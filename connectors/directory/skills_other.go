//go:build !linux

package main

import (
	"errors"
	"siq-agent-security/edge/agent/protocol"
)

const supportsSkillCollection = false

func collectSkills(protocol.ScanPlan) (protocol.SkillCollection, error) {
	return protocol.SkillCollection{}, errors.New("skill collection unsupported on this platform")
}

func collectSkillsVersion(protocol.ScanPlan, bool) (protocol.SkillCollection, error) {
	return protocol.SkillCollection{}, errors.New("skill collection unsupported on this platform")
}
