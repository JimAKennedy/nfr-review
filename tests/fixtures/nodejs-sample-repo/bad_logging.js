// Direct console.log usage
function debugInfo() {
  console.log('Starting process...');
  console.log('Config loaded');
}

// Console.warn and error
function handleWarnings() {
  console.warn('Deprecated API used');
  console.error('Something went wrong');
}

// Console.info
function statusUpdate() {
  console.info('Server started on port 3000');
}

// process.stdout.write
function rawOutput() {
  process.stdout.write('Progress: 50%\n');
}

// process.stderr.write
function rawError() {
  process.stderr.write('ERROR: connection lost\n');
}
