def calculate_checksum(digits: str, algorithm: str) -> str:
    """Calculate a checksum digit using a named algorithm."""
    if algorithm == 'luhn':
        total = sum(luhn_digit(index, digit) for index, digit in enumerate(reversed(digits)))
        return str((10 - total % 10) % 10)
    if algorithm == 'mod11':
        weights = [2, 3, 4, 5, 6, 7]
        total = sum(int(d) * weights[i % len(weights)] for i, d in enumerate(reversed(digits)))
        return mod11_digit(total % 11)
    total = sum(int(digit) for digit in digits)
    return str((10 - total % 10) % 10) if algorithm == 'mod10' else str(total % 10)


def luhn_digit(index: int, digit: str) -> int:
    """Return a transformed digit contribution for Luhn checksum."""
    value = int(digit) * (2 if index % 2 == 0 else 1)
    return value - 9 if value > 9 else value


def mod11_digit(remainder: int) -> str:
    """Return the canonical MOD11 check digit for a remainder."""
    return '0' if remainder == 0 else 'X' if remainder == 1 else str(11 - remainder)
