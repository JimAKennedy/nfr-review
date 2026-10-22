use std::sync::{Mutex, RwLock};

struct Shared {
    counter: Mutex<i32>,
    config: RwLock<String>,
}

impl Shared {
    fn bump(&self) {
        let mut guard = self.counter.lock().unwrap();
        *guard += 1;
    }

    fn read_config(&self) -> String {
        let guard = self.config.read().unwrap();
        guard.clone()
    }

    fn write_config(&self, value: String) {
        let mut guard = self.config.write().unwrap();
        *guard = value;
    }
}
