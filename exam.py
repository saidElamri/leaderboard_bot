def ft_is_even(n):
    return n % 2 == 0

def ft_last_char(s):
    return s[-2]

def ft_count_vowels(s):
    return sum(1 for c in s.lower() if c in "aeiou")
