const fs = require('fs');

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

function loadConfig() {
    fetch('/api/config').then(r => r.json());
}

function readSync() {
    return fs.readFileSync('/etc/config.json', 'utf-8');
}

module.exports = { processData, logToConsole, loadConfig, readSync };
