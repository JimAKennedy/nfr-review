package com.example;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class PaymentController {

    @PostMapping("/payments")
    public String processPayment(@RequestBody String payload) {
        return "{\"status\": \"accepted\"}";
    }
}
