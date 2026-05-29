package util

import "go-class-diagram/plugin"

// EventBus dispatches events to plugins (dependency via parameter).
type EventBus struct{}

// Dispatch sends an event to a plugin.
func (eb *EventBus) Dispatch(p plugin.Plugin, event string) {}
