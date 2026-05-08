const fs = require('fs');
const child_process = require('child_process');

// Floating promise - no await, no catch
async function fetchData() {
  fetch('/api/data');
}

// Fire-and-forget async call
function triggerJob() {
  processInBackground();
}

async function processInBackground() {
  await fetch('/api/process');
}

// Synchronous file system calls
function readConfig() {
  const data = fs.readFileSync('/etc/config.json');
  fs.writeFileSync('/tmp/output.txt', data);
  fs.appendFileSync('/tmp/log.txt', 'done\n');
  return data;
}

// Synchronous child_process calls
function runCommand() {
  const result = child_process.execSync('ls -la');
  return result;
}

// Promise chain without catch
function loadUser() {
  fetch('/api/user')
    .then(r => r.json())
    .then(data => data.user);
}

// Promise chain with catch
function loadUserSafe() {
  fetch('/api/user')
    .then(r => r.json())
    .catch(e => console.error(e));
}

// Callback without error check
fs.readFile('/etc/config.json', function(err, data) {
  console.log(data.toString());
});

// Callback with error check
fs.readFile('/etc/hosts', function(err, data) {
  if (err) throw err;
  console.log(data.toString());
});

// Arrow callback without error check
fs.readFile('/tmp/file.txt', (error, data) => {
  console.log(data);
});
