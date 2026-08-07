use std::sync::Mutex;
use std::time::Duration;

fn parse_config(raw: &str) -> Result<i32, std::num::ParseIntError> {
    raw.parse::<i32>()
}

struct Counter {
    value: Mutex<i32>,
}

impl Counter {
    fn increment(&self) -> Result<(), String> {
        let mut guard = self.value.lock().map_err(|e| e.to_string())?;
        *guard += 1;
        Ok(())
    }
}

fn build_client() -> Result<reqwest::Client, reqwest::Error> {
    reqwest::Client::builder().timeout(Duration::from_secs(10)).build()
}

async fn fetch_data() -> String {
    tokio::time::sleep(Duration::from_millis(100)).await;
    String::from("done")
}

async fn spawn_task() {
    let handle = tokio::spawn(async { 42 });
    let _ = handle.await;
}
