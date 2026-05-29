package com.example.util;

import com.example.plugin.Plugin;

public class EventBus {
    public void dispatch(Plugin target, String event) {
        target.activate();
    }

    public Plugin findPlugin(String name) {
        return null;
    }
}
