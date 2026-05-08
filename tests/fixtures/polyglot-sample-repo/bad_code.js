function processData(items) {
    try {
        JSON.parse(items);
    } catch (e) {
        // empty catch block
    }
}

function logToConsole(message) {
    console.log("DEBUG: " + message);
}

module.exports = { processData, logToConsole };
