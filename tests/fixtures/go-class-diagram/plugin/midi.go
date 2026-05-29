package plugin

// MidiPlugin handles MIDI input/output.
type MidiPlugin struct {
	channel int
}

// Activate opens the MIDI port.
func (m *MidiPlugin) Activate() {}

// Deactivate closes the MIDI port.
func (m *MidiPlugin) Deactivate() {}

// Editor is a nested type for editing MIDI events.
type Editor struct {
	trackName string
}

// Edit modifies a MIDI event.
func (ed *Editor) Edit(event string) {}
