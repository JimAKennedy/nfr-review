package plugin

// AudioPlugin plays audio content.
type AudioPlugin struct {
	volume float64
}

// Activate starts the audio subsystem.
func (a *AudioPlugin) Activate() {}

// Deactivate stops the audio subsystem.
func (a *AudioPlugin) Deactivate() {}

// SetVolume adjusts the playback volume.
func (a *AudioPlugin) SetVolume(level float64) {
	a.volume = level
}

// Preset is a nested type representing an audio preset.
type Preset struct {
	Name string
	Gain float64
}
