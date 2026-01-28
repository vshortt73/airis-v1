"""
TTS Text Normalizer

Converts text into speakable form for TTS systems.
Handles technical terms, acronyms, numbers, and abbreviations
that TTS systems typically mispronounce.
"""

import re
from typing import Dict, List, Tuple

# Number words for conversion
ONES = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
        'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
        'seventeen', 'eighteen', 'nineteen']
TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']

def number_to_words(n: int) -> str:
    """Convert integer to words (0-9999)."""
    if n < 0:
        return 'negative ' + number_to_words(-n)
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ('' if n % 10 == 0 else ' ' + ONES[n % 10])
    if n < 1000:
        return ONES[n // 100] + ' hundred' + ('' if n % 100 == 0 else ' ' + number_to_words(n % 100))
    if n < 10000:
        return number_to_words(n // 1000) + ' thousand' + ('' if n % 1000 == 0 else ' ' + number_to_words(n % 1000))
    # For larger numbers, just spell out digits
    return ' '.join(ONES[int(d)] if d != '0' else 'zero' for d in str(n))


def gpu_number_to_words(num_str: str) -> str:
    """
    Convert GPU model numbers to speakable form.
    5090 -> "fifty ninety"
    4080 -> "forty eighty"
    3060 -> "thirty sixty"
    """
    n = int(num_str)
    if 1000 <= n <= 9999:
        # Split into two parts: 50-90, 40-80, etc.
        first_two = n // 100
        last_two = n % 100

        first_word = number_to_words(first_two)
        last_word = number_to_words(last_two) if last_two > 0 else ""

        return f"{first_word} {last_word}".strip()
    return number_to_words(n)


# GPU brand prefixes - spell out as letters
GPU_PREFIXES = {
    'RTX': 'R T X',
    'GTX': 'G T X',
    'RX': 'R X',
    'RX ': 'R X ',
    'NVIDIA': 'Nvidia',
    'AMD': 'A M D',
    'INTEL': 'Intel',
    'ARC': 'Arc',
}

# Storage/memory units
STORAGE_UNITS = {
    'GB': 'gigabytes',
    'TB': 'terabytes',
    'MB': 'megabytes',
    'KB': 'kilobytes',
    'GiB': 'gibibytes',
    'TiB': 'tebibytes',
    'MiB': 'mebibytes',
}

# Tech acronyms - spell as letters
SPELL_OUT_ACRONYMS = [
    'API', 'GPU', 'CPU', 'RAM', 'SSD', 'HDD', 'NVMe', 'USB', 'HDMI',
    'HTTP', 'HTTPS', 'SSH', 'SQL', 'JSON', 'XML', 'HTML', 'CSS',
    'LLM', 'AI', 'ML', 'NLP', 'TTS', 'STT', 'ASR', 'OCR',
    'PDF', 'PNG', 'JPG', 'JPEG', 'GIF', 'MP3', 'MP4', 'WAV',
    'URL', 'URI', 'IP', 'TCP', 'UDP', 'DNS', 'VPN',
    'OS', 'CLI', 'GUI', 'IDE', 'SDK', 'NPM', 'PIP',
    'CUDA', 'VRAM', 'DDR', 'PCIe', 'BIOS', 'UEFI',
    'MCP', 'RAG', 'SNAC', 'GGUF', 'GGML',
]

# Pronounce as words (don't spell out)
PRONOUNCE_AS_WORDS = {
    'NVIDIA': 'Nvidia',
    'CUDA': 'Cuda',
    'XTTS': 'X T T S',
    'Ollama': 'Ollama',
    'PostgreSQL': 'Postgres Q L',
    'FastAPI': 'Fast A P I',
    'PyTorch': 'Pie Torch',
    'NumPy': 'Num Pie',
    'WiFi': 'Why Fy',
    'GHz': 'gigahertz',
    'MHz': 'megahertz',
    'kHz': 'kilohertz',
    'Hz': 'hertz',
    'fps': 'frames per second',
    'Mbps': 'megabits per second',
    'Gbps': 'gigabits per second',
}

# Common abbreviations
ABBREVIATIONS = {
    'vs': 'versus',
    'vs.': 'versus',
    'etc': 'et cetera',
    'etc.': 'et cetera',
    'e.g.': 'for example',
    'i.e.': 'that is',
    'approx': 'approximately',
    'approx.': 'approximately',
    'mins': 'minutes',
    'min': 'minutes',
    'secs': 'seconds',
    'sec': 'seconds',
    'hrs': 'hours',
    'hr': 'hour',
    'govt': 'government',
    'dept': 'department',
    'info': 'information',
    'admin': 'admin',
    'config': 'config',
    'auth': 'authentication',
    'dev': 'dev',
    'prod': 'production',
    'env': 'environment',
    'repo': 'repo',
    'dir': 'directory',
    'dirs': 'directories',
    'param': 'parameter',
    'params': 'parameters',
    'arg': 'argument',
    'args': 'arguments',
    'func': 'function',
    'async': 'async',
    'sync': 'sync',
    're:': 'regarding',
    'w/': 'with',
    'w/o': 'without',
    '&': 'and',
}


def spell_out(text: str) -> str:
    """Spell out text as individual letters with spaces."""
    return ' '.join(text.upper())


def normalize_gpu_models(text: str) -> str:
    """
    Normalize GPU model names.
    RTX5090 -> R T X fifty ninety
    GTX1080 -> G T X ten eighty
    RX7900 -> R X seventy nine hundred
    """
    # Pattern: GPU prefix + 3-4 digit number + optional suffix (Ti, Super, XT, etc.)
    # Use non-greedy matching and only consume space if suffix follows
    pattern = r'\b(RTX|GTX|RX)\s*(\d{3,4})(?:\s+(Ti|SUPER|Super|XT|XTX))?\b'

    def replace_gpu(match):
        prefix = match.group(1).upper()
        number = match.group(2)
        suffix = match.group(3) or ''

        prefix_spoken = GPU_PREFIXES.get(prefix, spell_out(prefix))
        number_spoken = gpu_number_to_words(number)

        # Handle suffixes
        suffix_spoken = ''
        if suffix:
            suffix_upper = suffix.upper()
            if suffix_upper == 'TI':
                suffix_spoken = 'T I'
            elif suffix_upper == 'SUPER':
                suffix_spoken = 'Super'
            elif suffix_upper in ('XT', 'XTX'):
                suffix_spoken = spell_out(suffix_upper)

        return f"{prefix_spoken} {number_spoken} {suffix_spoken}".strip()

    return re.sub(pattern, replace_gpu, text, flags=re.IGNORECASE)


def normalize_storage_units(text: str) -> str:
    """
    Normalize storage/memory sizes.
    32GB -> thirty two gigabytes
    1TB -> one terabyte
    512MB -> five hundred twelve megabytes
    """
    pattern = r'\b(\d+(?:\.\d+)?)\s*(GB|TB|MB|KB|GiB|TiB|MiB)\b'

    def replace_storage(match):
        number = match.group(1)
        unit = match.group(2)

        # Convert number
        if '.' in number:
            parts = number.split('.')
            num_word = number_to_words(int(parts[0])) + ' point ' + ' '.join(ONES[int(d)] for d in parts[1])
        else:
            num_word = number_to_words(int(number))

        # Get unit word
        unit_word = STORAGE_UNITS.get(unit, unit)

        # Handle singular
        if number == '1':
            unit_word = unit_word.rstrip('s')

        return f"{num_word} {unit_word}"

    return re.sub(pattern, replace_storage, text, flags=re.IGNORECASE)


def normalize_acronyms(text: str) -> str:
    """Spell out tech acronyms as letters."""
    for acronym in SPELL_OUT_ACRONYMS:
        # Match whole word only, case insensitive
        pattern = r'\b' + re.escape(acronym) + r'\b'
        replacement = spell_out(acronym)
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def normalize_special_words(text: str) -> str:
    """Handle special words that need specific pronunciation."""
    for word, replacement in PRONOUNCE_AS_WORDS.items():
        pattern = r'\b' + re.escape(word) + r'\b'
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def normalize_abbreviations(text: str) -> str:
    """Expand common abbreviations."""
    for abbrev, expansion in ABBREVIATIONS.items():
        # Be careful with word boundaries for abbreviations
        if abbrev.endswith('.'):
            pattern = re.escape(abbrev)
        else:
            pattern = r'\b' + re.escape(abbrev) + r'\b'
        text = re.sub(pattern, expansion, text, flags=re.IGNORECASE)
    return text


def normalize_version_numbers(text: str) -> str:
    """
    Normalize version numbers.
    v3.2.1 -> version three point two point one
    Python 3.10 -> Python three point ten
    """
    # Version with v prefix
    pattern = r'\bv(\d+(?:\.\d+)*)\b'

    def replace_version(match):
        version = match.group(1)
        parts = version.split('.')
        spoken_parts = [number_to_words(int(p)) for p in parts]
        return 'version ' + ' point '.join(spoken_parts)

    text = re.sub(pattern, replace_version, text, flags=re.IGNORECASE)

    return text


def normalize_standalone_numbers(text: str) -> str:
    """
    Convert standalone numbers to words where appropriate.
    Preserves numbers that are part of model names, versions, etc.
    """
    # Years (1900-2099) - keep as is, TTS usually handles these
    # Large numbers with commas
    pattern = r'\b(\d{1,3}(?:,\d{3})+)\b'

    def replace_comma_number(match):
        num_str = match.group(1).replace(',', '')
        n = int(num_str)
        if n < 10000:
            return number_to_words(n)
        # For larger numbers, let TTS handle it
        return match.group(0)

    text = re.sub(pattern, replace_comma_number, text)

    return text


def normalize_percentages(text: str) -> str:
    """Normalize percentages."""
    pattern = r'\b(\d+(?:\.\d+)?)\s*%'

    def replace_percent(match):
        num = match.group(1)
        if '.' in num:
            parts = num.split('.')
            num_word = number_to_words(int(parts[0])) + ' point ' + ' '.join(ONES[int(d)] for d in parts[1])
        else:
            num_word = number_to_words(int(num))
        return f"{num_word} percent"

    return re.sub(pattern, replace_percent, text)


def normalize_temperatures(text: str) -> str:
    """Normalize temperature readings."""
    pattern = r'\b(\d+(?:\.\d+)?)\s*°?\s*([CF])\b'

    def replace_temp(match):
        num = match.group(1)
        unit = match.group(2).upper()

        if '.' in num:
            parts = num.split('.')
            num_word = number_to_words(int(parts[0])) + ' point ' + ' '.join(ONES[int(d)] for d in parts[1])
        else:
            num_word = number_to_words(int(num))

        unit_word = 'Celsius' if unit == 'C' else 'Fahrenheit'
        return f"{num_word} degrees {unit_word}"

    return re.sub(pattern, replace_temp, text)


def normalize_for_tts(text: str) -> str:
    """
    Main normalization function. Applies all normalizations in order.

    Args:
        text: Raw text that may contain technical terms

    Returns:
        Normalized text suitable for TTS
    """
    if not text:
        return text

    # Apply normalizations in order (order matters!)
    # 1. Special words first (before acronym spelling)
    text = normalize_special_words(text)

    # 2. GPU models (before general acronyms)
    text = normalize_gpu_models(text)

    # 3. Storage units
    text = normalize_storage_units(text)

    # 4. Version numbers
    text = normalize_version_numbers(text)

    # 5. Percentages
    text = normalize_percentages(text)

    # 6. Temperatures
    text = normalize_temperatures(text)

    # 7. Acronyms (after GPU models to avoid double-processing)
    text = normalize_acronyms(text)

    # 8. Abbreviations
    text = normalize_abbreviations(text)

    # 9. Standalone numbers (last, to catch remaining)
    text = normalize_standalone_numbers(text)

    # Clean up multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()

    return text


# Quick test
if __name__ == "__main__":
    test_cases = [
        "I have an RTX5090 with 32GB of VRAM",
        "The RTX4080 Super is faster than the GTX1080Ti",
        "Check the API documentation at the URL",
        "It uses 50% of the GPU and 16GB RAM",
        "Python 3.10 with PyTorch and CUDA",
        "The temperature is 75°C under load",
        "Download the 1.5TB file via SSH",
        "Running at 144fps with 4K resolution",
        "Version v2.1.0 adds LLM support",
    ]

    for test in test_cases:
        print(f"Original: {test}")
        print(f"Normalized: {normalize_for_tts(test)}")
        print()
