package com.example.plugin;

public abstract class Plugin {
    protected String pluginName;

    public Plugin(String pluginName) {
        this.pluginName = pluginName;
    }

    public abstract void activate();

    public String getPluginName() {
        return pluginName;
    }
}
