package com.example;

import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Service
public class OrderService {

    private final RestTemplate restTemplate = new RestTemplate();

    public String fetchOrder(String id) {
        try {
            return restTemplate.getForObject("/orders/" + id, String.class);
        } catch (Exception e) {
            // exception swallowed — no rethrow
            return null;
        }
    }
}
