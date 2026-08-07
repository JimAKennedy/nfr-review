async fn call_service() {
    let client = reqwest::Client::new();
    let _ = client.get("https://example.com").send().await;
}

async fn call_service_builder() {
    let client = reqwest::Client::builder().build().unwrap();
    let _ = client.get("https://example.com").send().await;
}
