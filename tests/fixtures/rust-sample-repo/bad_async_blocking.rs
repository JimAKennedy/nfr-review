async fn fetch_data() -> String {
    std::thread::sleep(std::time::Duration::from_secs(1));
    let contents = std::fs::read_to_string("data.txt").unwrap_or_default();
    contents
}
