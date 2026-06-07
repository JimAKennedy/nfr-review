package com.example;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OrderController {

    @GetMapping("/orders")
    public String listOrders() {
        return "[]";
    }

    @PostMapping("/orders/{id}")
    public String updateOrder(@PathVariable String id, @RequestBody String body) {
        return "{\"id\": \"" + id + "\"}";
    }
}
