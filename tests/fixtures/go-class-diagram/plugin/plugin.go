package plugin

// Plugin is the interface all plugins must implement.
type Plugin interface {
	Activate()
	Deactivate()
}
