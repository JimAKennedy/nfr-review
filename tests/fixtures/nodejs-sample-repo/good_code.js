const logger = require('./logger');
const fs = require('fs').promises;

// Proper async/await with try/catch and structured logging
async function fetchUserData(userId) {
  try {
    const response = await fetch(`/api/users/${userId}`);
    const data = await response.json();
    return data;
  } catch (error) {
    logger.error('Failed to fetch user', { userId, error: error.message });
    throw error;
  }
}

// Proper error handling with rethrow
async function processOrder(orderId) {
  try {
    const order = await getOrder(orderId);
    await validateOrder(order);
    await chargePayment(order);
    return { success: true };
  } catch (error) {
    logger.error('Order processing failed', { orderId, error: error.message });
    throw error;
  }
}

// Async file operations (not sync)
async function readConfiguration() {
  const data = await fs.readFile('/etc/config.json', 'utf-8');
  return JSON.parse(data);
}

// Proper callback with error checking
function readFileWithCallback(path, callback) {
  fs.readFile(path, (err, data) => {
    if (err) {
      callback(err);
      return;
    }
    callback(null, data);
  });
}

// Arrow function with proper error handling
const safeParse = async (input) => {
  try {
    const result = await parseInput(input);
    return result;
  } catch (error) {
    logger.warn('Parse failed', { error: error.message });
    throw error;
  }
};

class DataService {
  async getData(id) {
    try {
      const result = await this.repository.findById(id);
      return result;
    } catch (error) {
      logger.error('Data fetch failed', { id, error: error.message });
      throw error;
    }
  }
}
