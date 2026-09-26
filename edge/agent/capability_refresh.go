package main

import (
	"context"
	"log"
)

func emptyInstalledCapabilities() map[string]any {
	return map[string]any{"inventory_schema": "enterprise-installed-capabilities/v1", "protocol_version": "connector-protocol.v1", "connectors": []string{}, "connector_versions": map[string]string{}, "data_categories": []string{}}
}

// Failed verification withdraws availability, not historical assets. Cancellation
// does not send a misleading empty snapshot while the service is shutting down.
func heartbeatWithMeasurement(ctx context.Context, state *State, measure func(context.Context, *State) (map[string]any, error), send func(context.Context, map[string]any) error) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if len(state.DiscoveryPlan) == 0 && state.DiscoveryPlanSHA256 == "" {
		return send(ctx, nil) // Legacy device; not a measured enterprise installation.
	}
	caps, err := measure(ctx, state)
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if err != nil || caps == nil {
		log.Print("edge connector capabilities unverified; withdrawing availability, historical assets unchanged")
		caps = emptyInstalledCapabilities()
	}
	return send(ctx, caps)
}
