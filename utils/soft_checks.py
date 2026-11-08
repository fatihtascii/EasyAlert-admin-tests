class SoftChecks:
    """Kontrolleri ilk hatada durmadan toplar, sonunda hepsini birlikte raporlar.

    Kullanım (test içinde `soft` fixture'ı ile):
        soft.check(a == b, "a = b")
        ...
        soft.assert_all()
    """

    def __init__(self):
        self.failures: list[str] = []

    def check(self, ok: bool, msg: str):
        print(f"  [{'OK ' if ok else 'HATA'}] {msg}")
        if not ok:
            self.failures.append(msg)

    def assert_all(self):
        assert not self.failures, f"{len(self.failures)} tutarsızlık:\n- " + "\n- ".join(self.failures)
