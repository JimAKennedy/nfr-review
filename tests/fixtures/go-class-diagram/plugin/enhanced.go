package plugin

// EnhancedPlugin embeds AudioPlugin to inherit its behaviour.
type EnhancedPlugin struct {
	AudioPlugin
	extraFeature string
}

// Enhance does something extra.
func (ep *EnhancedPlugin) Enhance() {}
