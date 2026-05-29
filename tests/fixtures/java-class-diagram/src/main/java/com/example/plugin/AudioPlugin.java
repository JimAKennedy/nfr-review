package com.example.plugin;

import com.example.engine.Config;

public class AudioPlugin extends Plugin {
    private int sampleRate;
    private Config audioConfig;

    public AudioPlugin(String name, int sampleRate, Config audioConfig) {
        super(name);
        this.sampleRate = sampleRate;
        this.audioConfig = audioConfig;
    }

    @Override
    public void activate() {
        // activate audio processing
    }

    public int getSampleRate() {
        return sampleRate;
    }
}
