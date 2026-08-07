pub trait Shape {
    fn area(&self) -> f64;
    fn perimeter(&self) -> f64 {
        0.0
    }
}

pub struct Circle {
    pub radius: f64,
}

pub struct Square {
    pub side: f64,
    label: String,
}

impl Shape for Circle {
    fn area(&self) -> f64 {
        std::f64::consts::PI * self.radius * self.radius
    }
}

impl Circle {
    pub fn new(radius: f64) -> Self {
        Circle { radius }
    }
}

impl Shape for Square {
    fn area(&self) -> f64 {
        self.side * self.side
    }

    fn perimeter(&self) -> f64 {
        self.side * 4.0
    }
}
