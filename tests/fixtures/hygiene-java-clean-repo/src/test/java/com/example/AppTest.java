package com.example;

import org.junit.Test;
import static org.junit.Assert.assertNotNull;

public class AppTest {
    @Test
    public void testApp() {
        assertNotNull("App class should exist", new App());
    }
}
