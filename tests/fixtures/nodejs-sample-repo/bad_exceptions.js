// Bare catch - swallows error silently
function riskyOperation() {
  try {
    JSON.parse('{invalid}');
  } catch (e) {
    // swallowed
  }
}

// Catch with logging but no rethrow
function anotherRisky() {
  try {
    require('./missing-module');
  } catch (err) {
    console.error(err);
  }
}

// Catch with rethrow
function properHandler() {
  try {
    connectToDatabase();
  } catch (error) {
    console.error('Connection failed:', error);
    throw error;
  }
}

// Catch with logging
function loggedHandler() {
  try {
    processPayment();
  } catch (e) {
    console.log('Payment failed:', e.message);
  }
}
