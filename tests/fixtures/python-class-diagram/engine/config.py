"""Engine configuration — standalone class with typed fields."""


class Config:
    name: str
    max_threads: int
    debug_mode: bool

    def __init__(self, name: str, max_threads: int = 4, debug_mode: bool = False) -> None:
        self.name = name
        self.max_threads = max_threads
        self.debug_mode = debug_mode

    def validate(self) -> bool:
        return self.max_threads > 0
