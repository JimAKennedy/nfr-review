package com.example.logging;

public class ConsoleLogger implements Logger {
    private String prefix;

    public ConsoleLogger(String prefix) {
        this.prefix = prefix;
    }

    @Override
    public void log(String message) {
        System.out.println(prefix + ": " + message);
    }

    @Override
    public void error(String message, Exception cause) {
        System.err.println(prefix + " ERROR: " + message);
    }
}
