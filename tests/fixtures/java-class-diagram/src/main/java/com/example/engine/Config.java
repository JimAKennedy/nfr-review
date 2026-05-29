package com.example.engine;

public class Config {
    private String name;
    private int maxThreads;
    protected boolean debugMode;

    public Config(String name, int maxThreads) {
        this.name = name;
        this.maxThreads = maxThreads;
        this.debugMode = false;
    }

    public String getName() {
        return name;
    }

    public int getMaxThreads() {
        return maxThreads;
    }
}
