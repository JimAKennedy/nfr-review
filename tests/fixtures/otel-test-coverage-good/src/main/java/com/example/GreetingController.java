package com.example;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class GreetingController {

    @GetMapping("/greeting")
    public String getGreeting() {
        return "Hello, World!";
    }

    @PostMapping("/greeting")
    public String postGreeting(@RequestBody String name) {
        return "Hello, " + name + "!";
    }
}
