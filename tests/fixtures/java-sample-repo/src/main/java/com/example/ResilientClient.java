package com.example;

import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.github.resilience4j.retry.annotation.Retry;
import org.springframework.stereotype.Service;

@Service
public class ResilientClient {

    @CircuitBreaker(name = "externalService")
    @Retry(name = "externalService")
    public String callExternal() {
        return "response";
    }

    @CircuitBreaker(name = "paymentService")
    public String callPayment() {
        return "payment ok";
    }
}
