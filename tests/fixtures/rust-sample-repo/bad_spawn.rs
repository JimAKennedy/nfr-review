async fn spawn_many(n: usize) {
    for i in 0..n {
        tokio::spawn(async move {
            println!("{}", i);
        });
    }
}

async fn spawn_once() {
    let handle = tokio::spawn(async { 42 });
    let _ = handle.await;
}
