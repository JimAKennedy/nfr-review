package com.example;

import com.github.tomakehurst.wiremock.client.WireMock;
import com.github.tomakehurst.wiremock.junit5.WireMockExtension;
import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerRegistry;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;
import org.testcontainers.junit.jupiter.Testcontainers;

import static com.github.tomakehurst.wiremock.client.WireMock.aResponse;
import static com.github.tomakehurst.wiremock.client.WireMock.urlEqualTo;
import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Testcontainers
class OrderResilienceIT {

    @RegisterExtension
    static WireMockExtension wireMock = WireMockExtension.newInstance().build();

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private CircuitBreakerRegistry circuitBreakerRegistry;

    @Test
    void circuitBreaker_opensAfterFailures() throws Exception {
        wireMock.stubFor(WireMock.get(urlEqualTo("/downstream/orders"))
                .willReturn(aResponse().withStatus(500)));

        for (int i = 0; i < 5; i++) {
            mockMvc.perform(get("/orders")).andReturn();
        }

        CircuitBreaker cb = circuitBreakerRegistry.circuitBreaker("orderService");
        assertThat(cb.getState()).isEqualTo(CircuitBreaker.State.OPEN);
    }

    @Test
    void circuitBreaker_fallbackReturnsDefault() throws Exception {
        wireMock.stubFor(WireMock.get(urlEqualTo("/downstream/orders"))
                .willReturn(aResponse().withStatus(503)));

        mockMvc.perform(get("/orders"))
                .andExpect(status().isOk());
    }
}
