ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(ALPHABET)


def encode(number):
    if not isinstance(number, int) or number < 0:
        raise ValueError("El número a codificar debe ser un entero no negativo")

    if number == 0:
        return ALPHABET[0]

    digits = []
    while number > 0:
        number, remainder = divmod(number, BASE)
        digits.append(ALPHABET[remainder])

    return "".join(reversed(digits))


def decode(text):
    if not text:
        raise ValueError("El hash no puede estar vacío")

    value = 0
    for char in text:
        index = ALPHABET.find(char)
        if index == -1:
            raise ValueError(f"Carácter inválido en Base62: {char!r}")
        value = value * BASE + index

    return value
