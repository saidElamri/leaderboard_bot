import importlib

# Exercises (name + test cases)
exercises = [
    ("ft_is_even", [(2, True), (3, False)]),
    ("ft_last_char", [("hello", "o")]),
    ("ft_count_vowels", [("hello", 2)]),
    ("ft_reverse", [("abc", "cba")]),
    ("ft_factorial", [(5, 120), (0, 1)]),
    ("ft_fibonacci", [(6, 8), (1, 1)]),
    ("ft_max_min", [([3, 1, 7], (7, 1))]),
    ("ft_sort_list", [([3, 1, 2], [1, 2, 3])]),
    ("ft_is_palindrome", [("radar", True), ("hello", False)]),
    ("ft_unique_words", [("this is this", ["this", "is"])])
]

# Load student code
exam = importlib.import_module("exam")

def run_exam():
    for i, (fname, tests) in enumerate(exercises, start=1):
        func = getattr(exam, fname, None)
        if not func:
            print(f"❌ Exercise {i}: {fname} not found")
            break
        ok = True
        for inp, expected in tests:
            # Handle multiple args
            if isinstance(inp, tuple):
                result = func(*inp)
            else:
                result = func(inp)

            if result != expected:
                print(f"❌ Exercise {i}: {fname} failed on {inp}. Got {result}, expected {expected}")
                ok = False
                break
        if ok:
            print(f"✅ Exercise {i}: {fname} passed")
        else:
            break  # stop at first failure

if __name__ == "__main__":
    run_exam()
