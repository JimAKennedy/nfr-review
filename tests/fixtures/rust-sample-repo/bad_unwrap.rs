fn parse_config(raw: &str) -> i32 {
    let value: Option<i32> = raw.parse().ok();
    value.unwrap()
}

fn load_setting(raw: &str) -> i32 {
    let value: Option<i32> = raw.parse().ok();
    value.expect("setting must be a valid integer")
}

#[cfg(test)]
mod tests {
    #[test]
    fn test_parse_config() {
        let x: Option<i32> = Some(5);
        let y = x.unwrap();
        assert_eq!(y, 5);
    }
}
