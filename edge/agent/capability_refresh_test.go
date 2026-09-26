package main

import (
	"context"
	"errors"
	"reflect"
	"testing"
)

func TestHeartbeatMeasurementLifecycle(t *testing.T) {
	for _, name := range []string{"legacy", "verified", "missing", "nil_result", "cancelled", "send_failure"} {
		t.Run(name, func(t *testing.T) {
			state := &State{DiscoveryPlanSHA256: "present"}
			if name == "legacy" {
				state = &State{}
			}
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			calls, sends := 0, 0
			measured := map[string]any{"connectors": []string{"hermes"}}
			sendErr := errors.New("network failure")
			err := heartbeatWithMeasurement(ctx, state, func(context.Context, *State) (map[string]any, error) {
				calls++
				if name == "cancelled" {
					cancel()
				}
				if name == "missing" {
					return nil, errors.New("private diagnostic")
				}
				if name == "nil_result" {
					return nil, nil
				}
				return measured, nil
			}, func(_ context.Context, caps map[string]any) error {
				sends++
				if name == "legacy" && caps != nil {
					t.Error("legacy overwritten")
				}
				if (name == "missing" || name == "nil_result") && !reflect.DeepEqual(caps, emptyInstalledCapabilities()) {
					t.Error("failed probe kept old availability")
				}
				if name == "verified" && !reflect.DeepEqual(caps, measured) {
					t.Error("measurement lost")
				}
				if name == "send_failure" {
					return sendErr
				}
				return nil
			})
			if name == "legacy" && calls != 0 {
				t.Fatal("legacy probed")
			}
			if name == "cancelled" {
				if !errors.Is(err, context.Canceled) || sends != 0 {
					t.Fatal("cancelled heartbeat sent")
				}
				return
			}
			if sends != 1 {
				t.Fatal("heartbeat count")
			}
			if name == "send_failure" {
				if err != sendErr {
					t.Fatal("transport failure hidden")
				}
			} else if err != nil {
				t.Fatal(err)
			}
		})
	}
}
