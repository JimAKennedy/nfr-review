package com.example;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
public class UserService {
    private static final Logger logger = LoggerFactory.getLogger(UserService.class);
    public void processUser(String ssn) {
        logger.info("Processing SSN: 123-45-6789", ssn);
    }
}
