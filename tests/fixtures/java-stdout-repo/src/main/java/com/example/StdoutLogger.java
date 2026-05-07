package com.example;

public class StdoutLogger {

    public void debugWithPrintln(String message) {
        System.out.println("DEBUG: " + message);
    }

    public void errorWithStderr(String error) {
        System.err.println("ERROR: " + error);
    }

    public void formatOutput(String name, int count) {
        System.out.printf("Processing %s: %d items%n", name, count);
    }
}
