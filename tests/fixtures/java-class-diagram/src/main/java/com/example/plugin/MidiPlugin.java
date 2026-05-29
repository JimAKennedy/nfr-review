package com.example.plugin;

public class MidiPlugin extends Plugin {
    private int channel;

    public MidiPlugin(String name, int channel) {
        super(name);
        this.channel = channel;
    }

    @Override
    public void activate() {
        // activate MIDI processing
    }

    public int getChannel() {
        return channel;
    }

    public class Editor {
        private String title;

        public Editor(String title) {
            this.title = title;
        }

        public String getTitle() {
            return title;
        }
    }
}
