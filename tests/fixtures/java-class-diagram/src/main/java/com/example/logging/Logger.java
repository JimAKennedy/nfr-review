package com.example.logging;

public interface Logger {
    void log(String message);
    void error(String message, Exception cause);
}
