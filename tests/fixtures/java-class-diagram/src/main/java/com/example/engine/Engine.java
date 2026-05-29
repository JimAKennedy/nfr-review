package com.example.engine;

import com.example.logging.Logger;
import com.example.plugin.Plugin;

public class Engine {
    private Config config;
    private Logger logger;
    private List<Plugin> plugins;

    public Engine(Config config, Logger logger) {
        this.config = config;
        this.logger = logger;
        this.plugins = new ArrayList<>();
    }

    public void start() {
        logger.log("Engine starting with config: " + config.getName());
    }

    public void registerPlugin(Plugin plugin) {
        plugins.add(plugin);
    }

    public Config getConfig() {
        return config;
    }
}
